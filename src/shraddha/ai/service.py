"""The gate between the assistant and any language model.

Three things must be true before a byte leaves the computer (checked in this order):

===============  ==========================================================
``llm.enabled``  the user has not switched AI off
``llm.provider`` a real provider is configured (``gemini``)
``api key``      a key was found in the environment or the credential store
``allow_cloud``  the user has agreed, in the app, to send questions to Google
===============  ==========================================================

The service also owns the conversation window (last ``llm.history_turns`` exchanges),
one polite retry on rate limits, and the translation of everything that can go wrong into
a Hindi sentence the chat window can display. It never raises at the UI boundary: callers
get :class:`AiEvent` objects.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Iterator

from shraddha.ai import prompts
from shraddha.ai.base import AiError, AiEvent, ChatMessage, LlmProvider, module_available
from shraddha.ai.gemini import DEPENDENCY as GEMINI_DEPENDENCY
from shraddha.ai.gemini import GeminiProvider
from shraddha.ai.keys import resolve_api_key
from shraddha.config import LlmConfig
from shraddha.logging_setup import get_logger

log = get_logger("ai.service")

STATUS_OFF = "off"
STATUS_NO_PROVIDER = "no_provider"
STATUS_NO_SDK = "no_sdk"
STATUS_NO_KEY = "no_key"
STATUS_CONSENT = "consent_required"
STATUS_READY = "ready"

CONSENT_GRANT = "grant"
CONSENT_REVOKE = "revoke"

#: Seconds to wait before the single retry on a rate-limited request.
RETRY_DELAY_S = 1.0
MAX_RETRIES = 1

ProviderFactory = Callable[[LlmConfig], LlmProvider | None]


_TRAILING_PUNCTUATION = "\u0964.,!?;:\"'()[]"


def _normalise(text: str) -> str:
    """Lower-case, collapse spaces, drop punctuation - consent is matched exactly."""
    cleaned = text.strip().lower()
    for mark in _TRAILING_PUNCTUATION:
        cleaned = cleaned.replace(mark, " ")
    return " ".join(cleaned.split())


def consent_intent(text: str) -> str | None:
    """``"grant"`` / ``"revoke"`` / ``None`` for an exact consent command.

    Deliberately exact-match: a fuzzy match on "क्लाउड AI" would let a *question about*
    cloud AI silently turn the network on.
    """
    normalised = _normalise(text)
    if normalised in {_normalise(phrase) for phrase in prompts.REVOKE_PHRASES}:
        return CONSENT_REVOKE
    if normalised in {_normalise(phrase) for phrase in prompts.CONSENT_PHRASES}:
        return CONSENT_GRANT
    return None


class AiService:
    """Session-scoped AI helper: status, consent, history, streaming answers."""

    def __init__(
        self,
        llm: LlmConfig,
        provider: LlmProvider | None = None,
        provider_factory: ProviderFactory | None = None,
        system_prompt: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.llm = llm
        self._provider = provider
        self._provider_factory = provider_factory
        self._system_prompt = system_prompt or prompts.build_system_prompt()
        self._sleep = sleep
        self._history: list[ChatMessage] = []
        self.last_error: AiError | None = None

    # ------------------------------------------------------------------ status
    @property
    def provider(self) -> LlmProvider | None:
        if self._provider is None and self._provider_factory is not None:
            try:
                self._provider = self._provider_factory(self.llm)
            except Exception as exc:  # pragma: no cover - constructor guard
                log.warning("provider construction failed: %s", exc)
                return None
        return self._provider

    @property
    def enabled(self) -> bool:
        return bool(self.llm.enabled and self.llm.provider != "none")

    def status(self) -> str:
        """Ordered gate: switch -> provider -> library -> key -> consent."""
        if not self.enabled:
            return STATUS_OFF
        if self.llm.provider != "gemini":
            return STATUS_NO_PROVIDER
        if not module_available(GEMINI_DEPENDENCY):
            return STATUS_NO_SDK
        key, _source = resolve_api_key(extra_env=self.llm.api_key_env or None)
        if not key:
            return STATUS_NO_KEY
        if not self.llm.allow_cloud:
            return STATUS_CONSENT
        return STATUS_READY

    def status_message(self) -> str:
        """Hindi explanation of the current state (empty when ready)."""
        status = self.status()
        if status == STATUS_READY:
            return ""
        if status == STATUS_OFF:
            return prompts.CONSENT_NOTICE
        if status == STATUS_NO_KEY:
            return prompts.NO_KEY_NOTICE
        if status == STATUS_CONSENT:
            return prompts.CONSENT_NOTICE
        provider = self.provider
        reason = provider.availability()[1] if provider is not None else ""
        return reason or prompts.NO_KEY_NOTICE

    @property
    def ready(self) -> bool:
        return self.status() == STATUS_READY

    def consent_notice(self) -> str:
        return prompts.CONSENT_NOTICE

    def apply_consent(self, intent: str) -> str:
        """Update consent in memory and return the Hindi confirmation text."""
        if intent == CONSENT_REVOKE:
            self.llm.allow_cloud = False
            self.llm.enabled = False
            log.info("cloud AI consent revoked")
            return prompts.CONSENT_REVOKED
        self.llm.enabled = True
        self.llm.allow_cloud = True
        if self.llm.provider == "none":
            self.llm.provider = "gemini"
        log.info("cloud AI consent granted (provider=%s)", self.llm.provider)
        return prompts.CONSENT_GRANTED

    # ---------------------------------------------------------------- history
    @property
    def history(self) -> list[ChatMessage]:
        return list(self._history)

    def remember(self, role: str, text: str) -> None:
        cleaned = (text or "").strip()
        if not cleaned:
            return
        limit = max(0, int(self.llm.history_turns)) * 2
        if limit <= 0:
            # history_turns = 0 means "no context": nothing is remembered at all.
            self._history.clear()
            return
        self._history.append(ChatMessage(role=role, text=cleaned))
        if len(self._history) > limit:
            del self._history[:-limit]

    def reset(self) -> None:
        self._history.clear()

    def prompt_messages(self, text: str) -> list[ChatMessage]:
        """History plus the new question - exactly what gets sent."""
        messages = list(self._history)
        messages.append(ChatMessage(role="user", text=text))
        return messages

    # ------------------------------------------------------------------- ask
    def ask(self, text: str) -> Iterator[AiEvent]:
        """Stream an answer. Never raises; the last event is ``final`` or ``error``."""
        question = (text or "").strip()
        if not question:
            yield AiEvent(kind="error", text="सवाल खाली है।", detail="empty")
            return

        status = self.status()
        if status != STATUS_READY:
            yield AiEvent(kind="error", text=self.status_message(), detail=status)
            return

        provider = self.provider
        if provider is None:  # pragma: no cover - status() already covers this
            yield AiEvent(kind="error", text=prompts.NO_KEY_NOTICE, detail=STATUS_NO_PROVIDER)
            return

        messages = self.prompt_messages(question)
        chunks: list[str] = []
        attempt = 0
        while True:
            produced = False
            try:
                for chunk in provider.stream(messages, self._system_prompt):
                    produced = True
                    chunks.append(chunk)
                    yield AiEvent(kind="partial", text=chunk)
                break
            except AiError as err:
                self.last_error = err
                log.warning("AI call failed (%s): %s", err.code, err)
                if err.retryable and not produced and attempt < MAX_RETRIES:
                    attempt += 1
                    self._sleep(RETRY_DELAY_S)
                    continue
                yield AiEvent(kind="error", text=err.user_message(), detail=err.code)
                return
            except Exception as exc:
                log.exception("unexpected AI failure")
                self.last_error = AiError(str(exc), code="ai_error")
                yield AiEvent(kind="error", text=prompts.UNREACHABLE_NOTICE, detail="ai_error")
                return

        answer = "".join(chunks).strip()
        if not answer:
            yield AiEvent(
                kind="error",
                text="मॉडल ने खाली जवाब दिया। फिर से पूछिए।",
                detail="empty",
            )
            return
        self.remember("user", question)
        self.remember("assistant", answer)
        yield AiEvent(kind="final", text=answer)

    def ask_text(self, text: str) -> str:
        """Blocking answer for the CLI (``--ai-check``). Raises :class:`AiError`."""
        answer = ""
        for event in self.ask(text):
            if event.kind == "final":
                answer = event.text
            elif event.kind == "error":
                raise AiError(event.text, code=event.detail or "ai_error")
        if not answer:
            raise AiError("कोई जवाब नहीं मिला।", code="empty")
        return answer

    def close(self) -> None:
        if self._provider is not None:
            try:
                self._provider.close()
            except Exception as exc:  # pragma: no cover - teardown
                log.debug("provider close failed: %s", exc)
            self._provider = None

    def __enter__(self) -> AiService:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def create_provider(llm: LlmConfig) -> LlmProvider | None:
    """Build the configured provider (``None`` when AI is off/unsupported)."""
    if llm.provider == "gemini":
        return GeminiProvider(
            model=llm.model,
            fallback_model=llm.fallback_model or None,
            api_key_env=llm.api_key_env or None,
            timeout_s=llm.timeout_s,
            max_output_tokens=llm.max_output_tokens,
            temperature=llm.temperature,
        )
    return None


def make_service(llm: LlmConfig, **kwargs: object) -> AiService:
    """Service backed by the real provider."""
    return AiService(llm, provider_factory=create_provider, **kwargs)  # type: ignore[arg-type]


def seed_history(service: AiService, turns: Iterable[tuple[str, str]]) -> None:
    """Feed stored turns (role, text) into a fresh service, oldest first."""
    for role, text in turns:
        service.remember(role, text)


__all__ = [
    "CONSENT_GRANT",
    "CONSENT_REVOKE",
    "MAX_RETRIES",
    "RETRY_DELAY_S",
    "STATUS_CONSENT",
    "STATUS_NO_KEY",
    "STATUS_NO_PROVIDER",
    "STATUS_NO_SDK",
    "STATUS_OFF",
    "STATUS_READY",
    "AiService",
    "consent_intent",
    "create_provider",
    "make_service",
    "seed_history",
]
