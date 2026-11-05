"""Phase 3 - the gate, the history window and the streaming contract.

The provider is a fake: no SDK, no network, no key. What is verified here is the policy
that makes cloud AI safe to ship - the three-way gate, exact consent phrases, one polite
retry, and the promise that the service never raises at the UI boundary.
"""

from __future__ import annotations

import pytest

from shraddha.ai import service as service_module
from shraddha.ai.base import AiError, ChatMessage
from shraddha.ai.prompts import CONSENT_GRANTED, CONSENT_NOTICE, CONSENT_REVOKED
from shraddha.ai.service import (
    STATUS_CONSENT,
    STATUS_NO_KEY,
    STATUS_NO_PROVIDER,
    STATUS_NO_SDK,
    STATUS_OFF,
    STATUS_READY,
    AiService,
    consent_intent,
    create_provider,
    seed_history,
)
from shraddha.config import LlmConfig


# --------------------------------------------------------------------- fakes
class FakeProvider:
    name = "gemini"
    model = "gemini-flash-latest"

    def __init__(
        self,
        chunks: tuple[str, ...] = ("नमस्ते", " जी"),
        errors: tuple[Exception, ...] = (),
        availability: tuple[bool, str] = (True, ""),
        fail_after_first_chunk: Exception | None = None,
    ) -> None:
        self.chunks = chunks
        self.errors = list(errors)
        self.availability_result = availability
        self.fail_after_first_chunk = fail_after_first_chunk
        self.requests: list[tuple[list[ChatMessage], str | None]] = []
        self.closed = False

    def availability(self) -> tuple[bool, str]:
        return self.availability_result

    def stream(self, messages, system=None):
        self.requests.append((list(messages), system))
        if self.errors:
            raise self.errors.pop(0)
        for chunk in self.chunks:
            yield chunk
            if self.fail_after_first_chunk is not None:
                raise self.fail_after_first_chunk

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def ready_llm() -> LlmConfig:
    return LlmConfig(provider="gemini", enabled=True, allow_cloud=True)


@pytest.fixture(autouse=True)
def _pretend_everything_is_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_module, "module_available", lambda _name: True)
    monkeypatch.setattr(service_module, "resolve_api_key", lambda **_kw: ("AIzaTESTKEY", "env:GEMINI_API_KEY"))


def service(llm: LlmConfig, provider: FakeProvider | None = None, **kwargs) -> AiService:
    return AiService(llm, provider=provider or FakeProvider(), **kwargs)


def events(stream) -> list[tuple[str, str]]:
    return [(event.kind, event.text) for event in stream]


# --------------------------------------------------------------------- status
def test_a_fresh_install_is_off_and_silent() -> None:
    llm = LlmConfig()
    svc = service(llm)

    assert svc.status() == STATUS_OFF
    assert svc.ready is False
    assert svc.status_message() == CONSENT_NOTICE
    assert llm.provider == "none"  # nothing was mutated by asking


def test_enabled_without_a_key_is_no_key() -> None:
    svc = service(LlmConfig(provider="gemini", enabled=True, allow_cloud=True))
    service_module.resolve_api_key = lambda **_kw: (None, "none")  # type: ignore[assignment]
    try:
        assert svc.status() == STATUS_NO_KEY
        assert "API कुंजी" in svc.status_message()
    finally:
        service_module.resolve_api_key = lambda **_kw: ("AIzaTESTKEY", "env:GEMINI_API_KEY")  # type: ignore[assignment]


def test_missing_sdk_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_module, "module_available", lambda _name: False)
    svc = service(LlmConfig(provider="gemini", enabled=True, allow_cloud=True))
    assert svc.status() == STATUS_NO_SDK


def test_key_and_provider_without_consent_asks_for_consent() -> None:
    svc = service(LlmConfig(provider="gemini", enabled=True, allow_cloud=False))
    assert svc.status() == STATUS_CONSENT
    assert svc.status_message() == CONSENT_NOTICE


def test_everything_in_place_is_ready(ready_llm: LlmConfig) -> None:
    svc = service(ready_llm)
    assert svc.status() == STATUS_READY
    assert svc.ready is True
    assert svc.status_message() == ""


def test_an_unsupported_provider_is_not_ready() -> None:
    svc = service(LlmConfig(provider="local", enabled=True, allow_cloud=True))
    assert svc.status() == STATUS_NO_PROVIDER


# -------------------------------------------------------------------- consent
@pytest.mark.parametrize(
    "phrase", ["क्लाउड AI चालू करो", "क्लाउड AI ऑन करो", "Enable cloud AI", "turn on cloud ai"]
)
def test_grant_phrases_are_recognised(phrase: str) -> None:
    assert consent_intent(phrase) == "grant"


@pytest.mark.parametrize("phrase", ["क्लाउड AI बंद करो", "disable cloud AI", "Turn off cloud AI."])
def test_revoke_phrases_are_recognised(phrase: str) -> None:
    assert consent_intent(phrase) == "revoke"


@pytest.mark.parametrize(
    "phrase",
    ["क्लाउड AI क्या है", "cloud ai ke bare me batao", "मुझे AI चालू करना है क्या", "gemini क्या है"],
)
def test_questions_about_cloud_ai_do_not_grant_consent(phrase: str) -> None:
    """A question must never turn the network on."""
    assert consent_intent(phrase) is None


def test_apply_consent_switches_a_fresh_install_on() -> None:
    llm = LlmConfig()
    svc = service(llm)

    assert svc.apply_consent("grant") == CONSENT_GRANTED
    assert llm.enabled is True
    assert llm.allow_cloud is True
    assert llm.provider == "gemini"
    assert svc.status() == STATUS_READY


def test_apply_consent_can_be_revoked() -> None:
    llm = LlmConfig(provider="gemini", enabled=True, allow_cloud=True)
    svc = service(llm)

    assert svc.apply_consent("revoke") == CONSENT_REVOKED
    assert llm.enabled is False
    assert llm.allow_cloud is False
    assert svc.status() == STATUS_OFF


# -------------------------------------------------------------------- history
def test_history_records_a_finished_exchange(ready_llm: LlmConfig) -> None:
    svc = service(ready_llm)

    list(svc.ask("भारत की राजधानी क्या है?"))

    assert [(m.role, m.text) for m in svc.history] == [
        ("user", "भारत की राजधानी क्या है?"),
        ("assistant", "नमस्ते जी"),
    ]


def test_history_is_trimmed_to_the_configured_window() -> None:
    llm = LlmConfig(provider="gemini", enabled=True, allow_cloud=True, history_turns=1)
    svc = service(llm)

    for question in ("एक", "दो", "तीन"):
        list(svc.ask(question))

    assert [m.text for m in svc.history] == ["तीन", "नमस्ते जी"]


def test_history_can_be_zeroed() -> None:
    llm = LlmConfig(provider="gemini", enabled=True, allow_cloud=True, history_turns=0)
    svc = service(llm)
    list(svc.ask("एक"))
    assert svc.history == []


def test_the_question_is_sent_with_history_but_not_duplicated(ready_llm: LlmConfig) -> None:
    provider = FakeProvider()
    svc = service(ready_llm, provider)

    list(svc.ask("पहला सवाल"))
    list(svc.ask("दूसरा सवाल"))

    second = provider.requests[1][0]
    assert [m.text for m in second] == ["पहला सवाल", "नमस्ते जी", "दूसरा सवाल"]


def test_seed_history_and_reset(ready_llm: LlmConfig) -> None:
    svc = service(ready_llm)
    seed_history(svc, [("user", "पुराना"), ("assistant", "जवाब")])
    assert len(svc.history) == 2
    svc.reset()
    assert svc.history == []


def test_a_failed_answer_does_not_pollute_the_history(ready_llm: LlmConfig) -> None:
    svc = service(ready_llm, FakeProvider(errors=(AiError("boom", code="network"),)))
    list(svc.ask("सवाल"))
    assert svc.history == []


# ------------------------------------------------------------------ streaming
def test_partial_events_stream_then_a_final_answer(ready_llm: LlmConfig) -> None:
    svc = service(ready_llm)
    kinds = events(svc.ask("नमस्ते"))
    assert kinds == [("partial", "नमस्ते"), ("partial", " जी"), ("final", "नमस्ते जी")]


def test_the_system_prompt_is_sent_with_every_request(ready_llm: LlmConfig) -> None:
    provider = FakeProvider()
    svc = service(ready_llm, provider)
    list(svc.ask("नमस्ते"))
    system = provider.requests[0][1] or ""
    assert "श्रद्धा" in system
    assert "कमांड" in system  # tells the model to stay out of PC actions


def test_an_empty_question_is_refused_without_a_request(ready_llm: LlmConfig) -> None:
    provider = FakeProvider()
    svc = service(ready_llm, provider)
    assert events(svc.ask("   ")) == [("error", "सवाल खाली है।")]
    assert provider.requests == []


def test_a_disabled_service_explains_itself_and_never_requests(ready_llm: LlmConfig) -> None:
    provider = FakeProvider()
    llm = LlmConfig()  # off
    svc = service(llm, provider)

    result = events(svc.ask("कुछ भी"))

    assert result[0][0] == "error"
    assert provider.requests == []


def test_a_network_error_becomes_one_hindi_error_event(ready_llm: LlmConfig) -> None:
    svc = service(ready_llm, FakeProvider(errors=(AiError("कनेक्शन नहीं", code="network"),)))

    result = events(svc.ask("सवाल"))

    assert len(result) == 1
    assert result[0][0] == "error"
    assert "कनेक्शन" in result[0][1]


def test_an_unexpected_exception_still_becomes_an_event(ready_llm: LlmConfig) -> None:
    svc = service(ready_llm, FakeProvider(errors=(RuntimeError("segfault-ish"),)))
    result = events(svc.ask("सवाल"))
    assert [kind for kind, _text in result] == ["error"]
    assert svc.last_error is not None


def test_a_rate_limit_is_retried_once(ready_llm: LlmConfig) -> None:
    sleeps: list[float] = []
    provider = FakeProvider(errors=(AiError("धीरे", code="rate_limited", retryable=True),))
    svc = service(ready_llm, provider, sleep=sleeps.append)

    result = events(svc.ask("सवाल"))

    assert result[-1] == ("final", "नमस्ते जी")
    assert sleeps == [service_module.RETRY_DELAY_S]
    assert len(provider.requests) == 2


def test_a_second_rate_limit_is_not_retried_forever(ready_llm: LlmConfig) -> None:
    sleeps: list[float] = []
    error = AiError("धीरे", code="rate_limited", retryable=True)
    provider = FakeProvider(errors=(error, AiError("धीरे", code="rate_limited", retryable=True)))
    svc = service(ready_llm, provider, sleep=sleeps.append)

    result = events(svc.ask("सवाल"))

    assert result[-1][0] == "error"
    assert len(sleeps) == service_module.MAX_RETRIES
    assert len(provider.requests) == 2


def test_a_failure_after_the_first_chunk_is_not_retried(ready_llm: LlmConfig) -> None:
    sleeps: list[float] = []
    provider = FakeProvider(
        errors=(),
        fail_after_first_chunk=AiError("अचानक", code="rate_limited", retryable=True),
    )
    svc = service(ready_llm, provider, sleep=sleeps.append)

    result = events(svc.ask("सवाल"))

    assert [kind for kind, _ in result] == ["partial", "error"]
    assert sleeps == []
    assert len(provider.requests) == 1


def test_ask_text_returns_the_joined_answer(ready_llm: LlmConfig) -> None:
    svc = service(ready_llm)
    assert svc.ask_text("नमस्ते") == "नमस्ते जी"


def test_ask_text_raises_the_error(ready_llm: LlmConfig) -> None:
    svc = service(ready_llm, FakeProvider(errors=(AiError("नहीं", code="network"),)))
    with pytest.raises(AiError) as caught:
        svc.ask_text("नमस्ते")
    assert caught.value.code == "network"


# ------------------------------------------------------------------- provider
def test_the_provider_is_built_lazily() -> None:
    built: list[LlmConfig] = []

    def factory(llm: LlmConfig):
        built.append(llm)
        return FakeProvider()

    llm = LlmConfig(provider="gemini", enabled=True, allow_cloud=True)
    svc = AiService(llm, provider_factory=factory)

    assert built == []
    assert svc.status() == STATUS_READY  # status is a key/sdk check, not a client
    assert built == []
    list(svc.ask("सवाल"))
    assert len(built) == 1
    assert built[0] is llm


def test_a_broken_factory_does_not_crash_the_service(monkeypatch: pytest.MonkeyPatch) -> None:
    def factory(_llm):
        raise RuntimeError("no client for you")

    llm = LlmConfig(provider="gemini", enabled=True, allow_cloud=True)
    svc = AiService(llm, provider_factory=factory)
    assert svc.provider is None
    assert [event.kind for event in svc.ask("सवाल")] == ["error"]


def test_close_releases_the_provider(ready_llm: LlmConfig) -> None:
    provider = FakeProvider()
    svc = service(ready_llm, provider)
    list(svc.ask("सवाल"))
    svc.close()
    assert provider.closed is True


def test_create_provider_only_builds_gemini() -> None:
    assert create_provider(LlmConfig(provider="none")) is None
    assert create_provider(LlmConfig(provider="local")) is None
    provider = create_provider(LlmConfig(provider="gemini", model="gemini-x"))
    assert provider is not None
    assert provider.model == "gemini-x"
    provider.close()


def test_service_works_as_a_context_manager(ready_llm: LlmConfig) -> None:
    provider = FakeProvider()
    with service(ready_llm, provider) as svc:
        assert svc.ready is True
    assert provider.closed is True
