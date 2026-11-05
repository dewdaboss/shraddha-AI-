"""Google Gemini provider, on the official ``google-genai`` SDK.

Design notes:

* the SDK is imported **inside** the provider, never at module import, so a user who has
  not opted in pays nothing (no import time, no memory);
* the model alias ``gemini-flash-latest`` is tried first and falls back **once** to
  ``gemini-2.5-flash`` when Google answers 404 for the alias - aliases move, and a
  phase-3 assistant should not break because a model was retired;
* every SDK/transport exception is translated into an :class:`AiError` with a Hindi
  sentence, so the UI never shows a traceback or an English stack trace.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from shraddha.ai.base import AiError, ChatMessage, ClientFactory, module_available
from shraddha.ai.keys import mask_key, resolve_api_key
from shraddha.logging_setup import get_logger

log = get_logger("ai.gemini")

DEPENDENCY = "google.genai"

MESSAGES: dict[str, tuple[str, str]] = {
    "invalid_key": (
        "API कुंजी मान्य नहीं है।",
        "नई कुंजी जोड़िए: python -m shraddha --set-api-key",
    ),
    "forbidden": (
        "इस कुंजी के पास इस मॉडल का उपयोग करने की अनुमति नहीं है।",
        "Google AI Studio में प्रोजेक्ट की अनुमतियाँ जाँचिए।",
    ),
    "model_missing": (
        "यह मॉडल उपलब्ध नहीं है।",
        "config.json में llm.model बदलिए (जैसे gemini-2.5-flash)।",
    ),
    "rate_limited": (
        "अभी बहुत ज़्यादा अनुरोध हो गए हैं।",
        "एक-दो मिनट बाद फिर पूछिए - मुफ़्त स्तर पर प्रति मिनट सीमा है।",
    ),
    "quota": (
        "आज की मुफ़्त सीमा पूरी हो गई है।",
        "कल फिर कोशिश कीजिए, या अपने Google प्रोजेक्ट में बिलिंग चालू कीजिए।",
    ),
    "server_error": (
        "Google के सर्वर में गड़बड़ी है।",
        "थोड़ी देर बाद फिर कोशिश कीजिए।",
    ),
    "timeout": (
        "जवाब आने में बहुत देर लग गई।",
        "इंटरनेट धीमा हो सकता है; फिर कोशिश कीजिए।",
    ),
    "network": (
        "इंटरनेट उपलब्ध नहीं है, इसलिए क्लाउड AI से जवाब नहीं आ सका।",
        "कनेक्शन जाँचिए - तब तक स्थानीय जवाब मिलते रहेंगे।",
    ),
    "blocked": (
        "मॉडल ने इस अनुरोध का जवाब देने से मना कर दिया।",
        "सवाल दूसरे शब्दों में पूछिए।",
    ),
    "empty": (
        "मॉडल ने खाली जवाब दिया।",
        "फिर से पूछिए।",
    ),
    "sdk_missing": (
        "क्लाउड AI के लिए ज़रूरी लाइब्रेरी (google-genai) नहीं है।",
        "pip install -e \".[ai]\"",
    ),
    "no_key": (
        "कोई API कुंजी नहीं मिली।",
        "python -m shraddha --set-api-key (या GEMINI_API_KEY सेट कीजिए)",
    ),
}


def _error(code: str, *, retryable: bool = False, detail: str = "") -> AiError:
    message, hint = MESSAGES.get(code, ("क्लाउड AI में गड़बड़ी हुई।", ""))
    error = AiError(message, code=code, hint=hint, retryable=retryable)
    if detail:
        error.args = (*error.args, detail)
    return error


def translate_error(exc: Exception) -> AiError:
    """Map an SDK/transport exception onto a code + Hindi message.

    Works on duck-typed attributes so the mapping is testable without the SDK installed.
    """
    if isinstance(exc, AiError):
        return exc

    status = getattr(exc, "code", None)
    if isinstance(status, str):  # google.genai often uses enum-ish values
        status = getattr(status, "value", status)
    if not isinstance(status, int):
        alt = getattr(exc, "status_code", None)
        status = alt if isinstance(alt, int) else None

    text = str(exc).lower()
    name = type(exc).__name__.lower()

    if "api key not valid" in text or "api_key_invalid" in text or "invalid api key" in text:
        return _error("invalid_key")
    if status == 400:
        return _error("invalid_key")
    if status == 401:
        return _error("invalid_key")
    if status == 403:
        return _error("forbidden")
    if status == 404 or "is not found" in text or "not supported for generatecontent" in text:
        return _error("model_missing")
    if status == 429 or "resource_exhausted" in text or "rate limit" in text:
        if "quota" in text and "per day" in text:
            return _error("quota")
        return _error("rate_limited", retryable=True)
    if status is not None and 500 <= status < 600:
        return _error("server_error", retryable=True)
    if isinstance(exc, TimeoutError) or "timed out" in text or "timeout" in name:
        return _error("timeout", retryable=True)
    if "candidate" in text and ("blocked" in text or "safety" in text):
        return _error("blocked")
    if isinstance(exc, OSError) or "connection" in name or "connect" in text or "dns" in text:
        return _error("network", retryable=True)
    log.debug("unmapped AI exception %s: %s", type(exc).__name__, exc)
    return AiError("क्लाउड AI से जवाब नहीं आ सका।", code="ai_error", hint="फिर कोशिश कीजिए।")


@dataclass
class GeminiProvider:
    """Streaming Gemini client with one-level model fallback."""

    model: str = "gemini-flash-latest"
    fallback_model: str | None = "gemini-2.5-flash"
    api_key: str | None = None
    api_key_env: str | None = None
    timeout_s: int = 30
    max_output_tokens: int = 1_024
    temperature: float = 0.6
    client_factory: ClientFactory | None = None
    name: str = "gemini"

    def __post_init__(self) -> None:
        self._client: object | None = None
        self._active_model = self.model
        self._key_source = "none"
        self._key: str | None = self.api_key

    # ------------------------------------------------------------------ status
    @property
    def active_model(self) -> str:
        """The model that last answered (after any fallback)."""
        return self._active_model

    @property
    def key_source(self) -> str:
        return self._key_source

    def _resolve_key(self) -> str | None:
        if self._key:
            self._key_source = "explicit"
            return self._key
        key, source = resolve_api_key(extra_env=self.api_key_env)
        self._key, self._key_source = key, source
        return key

    def availability(self) -> tuple[bool, str]:
        if not module_available(DEPENDENCY):
            return False, f"{MESSAGES['sdk_missing'][0]} - {MESSAGES['sdk_missing'][1]}"
        if not self._resolve_key():
            return False, f"{MESSAGES['no_key'][0]} - {MESSAGES['no_key'][1]}"
        return True, ""

    # ------------------------------------------------------------------ client
    def _get_client(self) -> object:
        if self._client is not None:
            return self._client
        key = self._resolve_key()
        if not key:
            raise _error("no_key")
        if self.client_factory is not None:
            self._client = self.client_factory(key)
            return self._client
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - guarded by availability()
            raise _error("sdk_missing") from exc

        options = types.HttpOptions(timeout=int(self.timeout_s * 1000))
        self._client = genai.Client(api_key=key, http_options=options)
        log.info("gemini client ready (model=%s, key=%s)", self.model, mask_key(key))
        return self._client

    # ----------------------------------------------------------------- request
    def stream(self, messages: list[ChatMessage], system: str | None = None) -> Iterator[str]:
        """Yield answer chunks, falling back once if the model alias is unknown."""
        models = [self.model]
        if self.fallback_model and self.fallback_model != self.model:
            models.append(self.fallback_model)

        last_error: AiError | None = None
        for index, model in enumerate(models):
            produced = False
            try:
                for chunk in self._stream_once(model, messages, system):
                    produced = True
                    yield chunk
                self._active_model = model
                if index:
                    log.info("gemini answered with fallback model %s", model)
                return
            except AiError as exc:
                last_error = exc
                # Only a *model* problem justifies a silent retry, and only before any
                # text reached the user (otherwise the answer would be duplicated).
                if exc.code == "model_missing" and not produced and index + 1 < len(models):
                    log.warning("model %s unavailable, retrying with %s", model, models[index + 1])
                    continue
                raise
        if last_error is not None:  # pragma: no cover - defensive
            raise last_error
        raise _error("empty")

    def _stream_once(
        self, model: str, messages: list[ChatMessage], system: str | None
    ) -> Iterator[str]:
        client = self._get_client()
        contents = [
            {"role": "user" if message.is_user else "model", "parts": [{"text": message.text}]}
            for message in messages
        ]
        try:
            stream = client.models.generate_content_stream(  # type: ignore[attr-defined]
                model=model,
                contents=contents,
                config=self._config(system),
            )
            for chunk in stream:
                text = getattr(chunk, "text", None) or ""
                if text:
                    yield text
        except AiError:
            raise
        except Exception as exc:  # the SDK raises a zoo of types
            raise translate_error(exc) from exc

    def _config(self, system: str | None) -> object:
        try:
            from google.genai import types
        except ImportError:  # tests / provider built with a fake client
            return {
                "system_instruction": system,
                "temperature": self.temperature,
                "max_output_tokens": self.max_output_tokens,
            }
        return types.GenerateContentConfig(
            system_instruction=system,
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
        )

    # ---------------------------------------------------------------- non-stream
    def generate(self, messages: list[ChatMessage], system: str | None = None) -> str:
        text = "".join(self.stream(messages, system)).strip()
        if not text:
            raise _error("empty")
        return text

    def close(self) -> None:
        client, self._client = self._client, None
        closer = getattr(client, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception as exc:  # pragma: no cover - transport teardown
                log.debug("client close failed: %s", exc)


__all__ = ["DEPENDENCY", "MESSAGES", "GeminiProvider", "translate_error"]
