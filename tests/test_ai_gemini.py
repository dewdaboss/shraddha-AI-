"""Phase 3 - the AI provider layer, with no network and no real key.

Every request in this file goes to a fake client, so the suite is safe to run in CI with
no ``GEMINI_API_KEY`` set and no internet access.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from shraddha.ai import gemini as gemini_module
from shraddha.ai.base import AiError, ChatMessage, collect_stream, module_available
from shraddha.ai.gemini import GeminiProvider, translate_error
from shraddha.ai.keys import mask_key, resolve_api_key

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "shraddha" / "ai"


# --------------------------------------------------------------------- fakes
class FakeChunk:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeModels:
    """Records the request and replays scripted chunks (or raises)."""

    def __init__(self, script, calls: list[dict[str, object]] | None = None) -> None:
        self._script = script
        self.calls = calls if calls is not None else []

    def generate_content_stream(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        result = self._script(model) if callable(self._script) else self._script
        if isinstance(result, Exception):
            raise result
        for item in result:
            if isinstance(item, Exception):
                raise item
            yield item


class FakeClient:
    def __init__(self, models: FakeModels) -> None:
        self.models = models
        self.closed = False

    def close(self) -> None:
        self.closed = True


class ApiError(Exception):
    """Stand-in for ``google.genai.errors.APIError`` (duck-typed)."""

    def __init__(self, code: int, message: str, status: str = "") -> None:
        super().__init__(f"{code} {status} {message}".strip())
        self.code = code
        self.status = status


def build(script, **kwargs) -> tuple[GeminiProvider, FakeModels, FakeClient]:
    models = FakeModels(script)
    client = FakeClient(models)
    provider = GeminiProvider(api_key="AIzaTESTKEY0000000000000000000000000", client_factory=lambda _k: client, **kwargs)
    return provider, models, client


# ----------------------------------------------------------------- happy path
def test_streams_chunks_in_order() -> None:
    provider, _models, _client = build([FakeChunk("नमस्ते"), FakeChunk(" दुनिया")])

    chunks = list(provider.stream([ChatMessage("user", "hi")], "system"))

    assert chunks == ["नमस्ते", " दुनिया"]
    assert provider.generate([ChatMessage("user", "hi")], "system") == "नमस्ते दुनिया"
    assert provider.active_model == "gemini-flash-latest"


def test_request_shape_matches_the_sdk() -> None:
    provider, models, _client = build([FakeChunk("ठीक")])

    list(
        provider.stream(
            [ChatMessage("user", "पहला"), ChatMessage("assistant", "जवाब"), ChatMessage("user", "दूसरा")],
            "SYSTEM INSTRUCTION",
        )
    )

    call = models.calls[0]
    assert call["model"] == "gemini-flash-latest"
    assert call["contents"] == [
        {"role": "user", "parts": [{"text": "पहला"}]},
        {"role": "model", "parts": [{"text": "जवाब"}]},
        {"role": "user", "parts": [{"text": "दूसरा"}]},
    ]
    config = call["config"]
    system = config["system_instruction"] if isinstance(config, dict) else config.system_instruction
    assert system == "SYSTEM INSTRUCTION"


def test_backend_errors_never_escape_as_raw_exceptions() -> None:
    provider, _models, _client = build([ApiError(429, "quota exceeded", "RESOURCE_EXHAUSTED")])

    with pytest.raises(AiError) as caught:
        list(provider.stream([ChatMessage("user", "hi")]))

    assert caught.value.code == "rate_limited"
    assert "अनुरोध" in str(caught.value)


# ------------------------------------------------------------------- fallback
def test_unknown_model_falls_back_once() -> None:
    def script(model: str):
        if model == "gemini-flash-latest":
            return ApiError(404, "models/gemini-flash-latest is not found")
        return [FakeChunk("फ़ॉलबैक जवाब")]

    provider, models, _client = build(script)

    text = provider.generate([ChatMessage("user", "hi")])

    assert text == "फ़ॉलबैक जवाब"
    assert [call["model"] for call in models.calls] == ["gemini-flash-latest", "gemini-2.5-flash"]
    assert provider.active_model == "gemini-2.5-flash"


def test_no_fallback_after_text_reached_the_user() -> None:
    def script(_model: str):
        return [FakeChunk("आधा"), ApiError(404, "not found")]

    provider, models, _client = build(script)

    with pytest.raises(AiError):
        list(provider.stream([ChatMessage("user", "hi")]))
    assert len(models.calls) == 1  # a retry here would duplicate the sentence


def test_fallback_is_not_used_when_it_is_the_same_model() -> None:
    provider, models, _client = build(
        ApiError(404, "not found"), model="gemini-2.5-flash", fallback_model="gemini-2.5-flash"
    )
    with pytest.raises(AiError):
        list(provider.stream([ChatMessage("user", "hi")]))
    assert len(models.calls) == 1


def test_fallback_disabled_by_empty_string() -> None:
    provider, models, _client = build(ApiError(404, "not found"), fallback_model="")
    with pytest.raises(AiError):
        list(provider.stream([ChatMessage("user", "hi")]))
    assert len(models.calls) == 1


# ---------------------------------------------------------------- error codes
@pytest.mark.parametrize(
    ("exception", "code"),
    [
        (ApiError(400, "API key not valid. Please pass a valid API key."), "invalid_key"),
        (ApiError(401, "unauthenticated"), "invalid_key"),
        (ApiError(403, "permission denied"), "forbidden"),
        (ApiError(404, "model not found"), "model_missing"),
        (ApiError(429, "Resource has been exhausted (e.g. check quota)."), "rate_limited"),
        (ApiError(503, "service unavailable"), "server_error"),
        (TimeoutError("timed out"), "timeout"),
        (OSError("connection reset by peer"), "network"),
        (Exception("Candidate was blocked due to SAFETY"), "blocked"),
    ],
)
def test_translate_error_maps_to_a_hindi_code(exception: Exception, code: str) -> None:
    error = translate_error(exception)
    assert isinstance(error, AiError)
    assert error.code == code
    assert error.hint  # every code carries an actionable hint


def test_rate_limit_is_retryable_but_invalid_key_is_not() -> None:
    assert translate_error(ApiError(429, "rate limit")).retryable is True
    assert translate_error(ApiError(400, "bad key")).retryable is False


def test_daily_quota_is_reported_differently() -> None:
    error = translate_error(ApiError(429, "quota exceeded per day"))
    assert error.code == "quota"
    assert error.retryable is False


def test_translate_error_passes_ai_error_through() -> None:
    original = AiError("already translated", code="network")
    assert translate_error(original) is original


# -------------------------------------------------------------- availability
def test_availability_reports_a_missing_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gemini_module, "module_available", lambda _name: False)
    provider = GeminiProvider(api_key="AIzaKEY")
    ready, reason = provider.availability()
    assert ready is False
    assert "google-genai" in reason


def test_availability_reports_a_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gemini_module, "module_available", lambda _name: True)
    monkeypatch.setattr(gemini_module, "resolve_api_key", lambda **_kw: (None, "none"))
    provider = GeminiProvider()
    ready, reason = provider.availability()
    assert ready is False
    assert "API कुंजी" in reason


def test_availability_is_true_without_building_a_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gemini_module, "module_available", lambda _name: True)
    built: list[str] = []
    provider = GeminiProvider(
        api_key="AIzaTESTKEY",
        client_factory=lambda key: built.append(key) or FakeClient(FakeModels([])),
    )

    ready, reason = provider.availability()

    assert (ready, reason) == (True, "")
    assert built == []  # no socket, no client, just a fact check


def test_client_is_built_once_and_key_is_resolved_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaFROMENV")
    keys: list[str] = []

    def factory(key: str) -> FakeClient:
        keys.append(key)
        return FakeClient(FakeModels([FakeChunk("ok")]))

    provider = GeminiProvider(client_factory=factory)

    provider.generate([ChatMessage("user", "a")])
    provider.generate([ChatMessage("user", "b")])

    assert keys == ["AIzaFROMENV"]
    assert provider.key_source == "env:GEMINI_API_KEY"


def test_close_releases_the_client() -> None:
    provider, _models, client = build([FakeChunk("ok")])
    provider.generate([ChatMessage("user", "a")])

    provider.close()

    assert client.closed is True
    assert provider._client is None


def test_empty_answer_is_an_error() -> None:
    provider, _models, _client = build([FakeChunk("")])
    with pytest.raises(AiError) as caught:
        provider.generate([ChatMessage("user", "a")])
    assert caught.value.code == "empty"


def test_collect_stream_helper() -> None:
    provider, _models, _client = build([FakeChunk(" एक"), FakeChunk(" दो")])
    assert collect_stream(provider, [ChatMessage("user", "a")]) == "एक दो"


# ------------------------------------------------------------------ key handling
def test_key_precedence_prefers_gemini_then_google_then_credential() -> None:
    env = {"GEMINI_API_KEY": "primary", "GOOGLE_API_KEY": "secondary"}
    assert resolve_api_key(env, credential_reader=lambda: "stored") == ("primary", "env:GEMINI_API_KEY")
    assert resolve_api_key({"GOOGLE_API_KEY": "secondary"}, credential_reader=lambda: "stored") == (
        "secondary",
        "env:GOOGLE_API_KEY",
    )
    assert resolve_api_key({}, credential_reader=lambda: "stored") == ("stored", "credential")
    assert resolve_api_key({}, credential_reader=lambda: None) == (None, "none")


def test_custom_env_name_is_honoured_first() -> None:
    env = {"MY_KEY": "custom", "GEMINI_API_KEY": "primary"}
    assert resolve_api_key(env, credential_reader=lambda: None, extra_env="MY_KEY") == (
        "custom",
        "env:MY_KEY",
    )


def test_blank_values_are_ignored() -> None:
    env = {"GEMINI_API_KEY": "   ", "GOOGLE_API_KEY": ""}
    assert resolve_api_key(env, credential_reader=lambda: "  ") == (None, "none")


def test_a_broken_credential_store_does_not_raise() -> None:
    def explode() -> str:
        raise RuntimeError("COM exploded")

    assert resolve_api_key({}, credential_reader=explode) == (None, "none")


def test_mask_key_never_reveals_the_whole_key() -> None:
    assert mask_key(None) == "(none)"
    assert mask_key("short") == "*****"
    masked = mask_key("AIzaSyCD1234567890abcdefghijklmnop4f2c")
    assert masked.endswith("4f2c")
    assert "AIza" not in masked
    assert len(masked) < len("AIzaSyCD1234567890abcdefghijklmnop4f2c")


# --------------------------------------------------------- capability boundary
def _imported_modules(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.add(node.module.split(".")[0])
    return names


def test_the_ai_package_cannot_act_on_the_computer() -> None:
    """A model must never be able to run a command, open an app, or touch the disk."""
    forbidden = {"subprocess", "shlex", "ctypes", "shraddha.commands", "shraddha.shell"}
    offenders = {}
    for path in SRC.glob("*.py"):
        bad = _imported_modules(path) & forbidden
        if bad:
            offenders[path.name] = sorted(bad)
    assert offenders == {}


def test_the_sdk_is_imported_lazily() -> None:
    """Module import must not drag in google-genai (or its ~1 s import cost)."""
    for path in SRC.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:  # only top-level imports are eager
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("google"):
                pytest.fail(f"{path.name} imports the SDK at module level")
            if isinstance(node, ast.Import) and any(
                alias.name.startswith("google") for alias in node.names
            ):
                pytest.fail(f"{path.name} imports the SDK at module level")


def test_module_available_is_cheap_and_correct() -> None:
    assert module_available("json") is True
    assert module_available("shraddha_definitely_not_installed") is False
