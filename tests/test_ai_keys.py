"""Phase 3 - the Windows Credential Manager path, exercised without Windows.

A fake ``win32cred`` module is injected into ``sys.modules``, so the store/report logic
is covered on every platform and CI still never sees a real key.
"""

from __future__ import annotations

import sys
import types

import pytest

from shraddha.ai import key_report, provider_status
from shraddha.ai import keys as keys_module
from shraddha.ai.keys import (
    CREDENTIAL_TARGET,
    KeyStoreError,
    credential_support,
    delete_credential,
    read_credential,
    write_credential,
)
from shraddha.config import LlmConfig


class FakeWin32Cred(types.ModuleType):
    """Minimal stand-in for ``win32cred``."""

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    def __init__(self, blob: bytes | None = b"", fail_on: str | None = None) -> None:
        super().__init__("win32cred")
        self.blob = blob
        self.fail_on = fail_on
        self.written: list[dict[str, object]] = []
        self.deleted: list[tuple[str, int, int]] = []

    def CredRead(self, target, _type):
        assert target == CREDENTIAL_TARGET
        if self.fail_on == "read" or self.blob is None:
            raise OSError("element not found")
        return {"CredentialBlob": self.blob, "UserName": "shraddha-ai"}

    def CredWrite(self, entry, _flags):
        if self.fail_on == "write":
            raise OSError("access denied")
        self.written.append(entry)

    def CredDelete(self, target, _type, _flags):
        if self.fail_on == "delete":
            raise OSError("element not found")
        self.deleted.append((target, _type, _flags))


@pytest.fixture()
def fake_store(monkeypatch: pytest.MonkeyPatch):
    module = FakeWin32Cred()
    monkeypatch.setitem(sys.modules, "win32cred", module)
    monkeypatch.setattr(keys_module, "credential_support", lambda: (True, ""))
    return module


def test_support_is_reported_as_unavailable_without_pywin32() -> None:
    ready, reason = credential_support()
    assert ready is False
    assert reason  # a sentence, not an exception


def test_read_returns_the_stored_key(fake_store) -> None:
    fake_store.blob = b"AIzaSTOREDKEY0000000000000000000001"
    assert read_credential() == "AIzaSTOREDKEY0000000000000000000001"


def test_read_returns_none_when_nothing_is_stored(fake_store) -> None:
    fake_store.blob = None
    assert read_credential() is None


def test_read_handles_a_text_blob(fake_store) -> None:
    fake_store.blob = "AIzaTEXTBLOB"
    assert read_credential() == "AIzaTEXTBLOB"


def test_read_is_none_when_the_store_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keys_module, "credential_support", lambda: (False, "nope"))
    assert read_credential() is None


def test_write_stores_a_generic_credential(fake_store) -> None:
    write_credential("  AIzaNEWKEY1234  ")

    entry = fake_store.written[0]
    assert entry["TargetName"] == CREDENTIAL_TARGET
    assert entry["Type"] == fake_store.CRED_TYPE_GENERIC
    assert entry["CredentialBlob"] == "AIzaNEWKEY1234"  # whitespace trimmed
    assert entry["Persist"] == fake_store.CRED_PERSIST_LOCAL_MACHINE


def test_write_rejects_an_empty_key(fake_store) -> None:
    with pytest.raises(KeyStoreError):
        write_credential("   ")
    assert fake_store.written == []


def test_write_reports_a_store_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    broken = FakeWin32Cred(fail_on="write")
    monkeypatch.setitem(sys.modules, "win32cred", broken)
    monkeypatch.setattr(keys_module, "credential_support", lambda: (True, ""))
    with pytest.raises(KeyStoreError):
        write_credential("AIzaKEY")


def test_write_explains_an_unavailable_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keys_module, "credential_support", lambda: (False, "pywin32 missing"))
    with pytest.raises(KeyStoreError) as caught:
        write_credential("AIzaKEY")
    assert "pywin32 missing" in str(caught.value)


def test_delete_reports_what_happened(fake_store) -> None:
    assert delete_credential() is True
    assert fake_store.deleted and fake_store.deleted[0][0] == CREDENTIAL_TARGET


def test_delete_is_false_when_nothing_is_stored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "win32cred", FakeWin32Cred(fail_on="delete"))
    monkeypatch.setattr(keys_module, "credential_support", lambda: (True, ""))
    assert delete_credential() is False


def test_delete_is_false_without_the_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keys_module, "credential_support", lambda: (False, "nope"))
    assert delete_credential() is False


# --------------------------------------------------------------- report helpers
def test_key_report_says_where_the_key_came_from(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaREPORTKEY0000000000000000009876")
    info = key_report(LlmConfig())
    assert info["present"] is True
    assert info["source"] == "env:GEMINI_API_KEY"
    assert info["masked"].endswith("9876")


def test_key_report_contains_no_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaREPORTKEY0000000000000000009876")
    info = key_report(LlmConfig())
    assert "AIzaREPORTKEY" not in str(info)


def test_provider_status_describes_an_unconfigured_install() -> None:
    info = provider_status(LlmConfig())
    assert info.name == "none"
    assert info.ready is False


def test_provider_status_builds_and_closes_a_gemini_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    import shraddha.ai as ai_package

    closed: list[bool] = []

    class FakeProvider:
        name = "gemini"

        def availability(self):
            return True, ""

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(ai_package, "create_provider", lambda _llm: FakeProvider())
    info = provider_status(LlmConfig(provider="gemini"))
    assert (info.name, info.ready) == ("gemini", True)
    assert closed == [True]
