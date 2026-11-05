"""API-key handling: environment first, Windows Credential Manager second.

Precedence is fixed and tested:

1. ``GEMINI_API_KEY``
2. ``GOOGLE_API_KEY``
3. Windows Credential Manager, target ``ShraddhaAI/GeminiApiKey``

The key is never written to ``config.json``, never logged, and never printed in full:
:func:`mask_key` is the only thing allowed near a log line or a report. Storage in the
Credential Manager uses ``win32cred`` from pywin32, which the ``win`` extra already
installs - so this adds no dependency.

Off Windows (and without pywin32) the credential functions degrade to "unavailable"
instead of raising, which keeps the doctor report honest and the tests portable.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping

from shraddha.logging_setup import get_logger

log = get_logger("ai.keys")

PRIMARY_ENV = "GEMINI_API_KEY"
SECONDARY_ENV = "GOOGLE_API_KEY"
#: Custom variable honoured through ``llm.api_key_env``.
CREDENTIAL_TARGET = "ShraddhaAI/GeminiApiKey"
CREDENTIAL_USER = "shraddha-ai"

SOURCE_PRIMARY = f"env:{PRIMARY_ENV}"
SOURCE_SECONDARY = f"env:{SECONDARY_ENV}"
SOURCE_CREDENTIAL = "credential"
SOURCE_NONE = "none"


class KeyStoreError(RuntimeError):
    """The credential store could not be used."""


def mask_key(key: str | None) -> str:
    """``…4f2c`` (last four characters only) - safe for logs, reports and errors.

    Nothing before the ellipsis is shown: a Gemini key is ~39 characters and its prefix
    is shared by every key, so only the suffix is worth printing anyway.
    """
    if not key:
        return "(none)"
    if len(key) <= 8:
        return "*" * len(key)
    return f"\u2026{key[-4:]}"


def _clean(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def credential_support() -> tuple[bool, str]:
    """``(available, reason)`` for the Windows Credential Manager."""
    try:
        import win32cred  # noqa: F401 - optional dependency
    except ImportError:
        return False, "pywin32 is not installed (pip install -e '.[win]')"
    except Exception as exc:  # pragma: no cover - broken COM install
        return False, str(exc)
    if os.name != "nt":
        return False, "the Windows Credential Manager only exists on Windows"
    return True, ""


def read_credential() -> str | None:
    """Read the stored key, or ``None`` when absent/unavailable."""
    available, reason = credential_support()
    if not available:
        log.debug("credential store unavailable: %s", reason)
        return None
    import win32cred

    try:
        entry = win32cred.CredRead(CREDENTIAL_TARGET, win32cred.CRED_TYPE_GENERIC)
    except Exception as exc:  # py_error for "not found" as well
        log.debug("no credential stored: %s", exc)
        return None
    if not isinstance(entry, dict):
        return None
    blob = entry.get("CredentialBlob")
    if isinstance(blob, bytes):
        return _clean(blob.decode("utf-8", "ignore"))
    return _clean(blob)


def write_credential(secret: str) -> None:
    """Store the key in the Credential Manager (Windows only)."""
    cleaned = _clean(secret)
    if not cleaned:
        raise KeyStoreError("the API key is empty")
    available, reason = credential_support()
    if not available:
        raise KeyStoreError(reason)
    import win32cred

    try:
        win32cred.CredWrite(
            {
                "Type": win32cred.CRED_TYPE_GENERIC,
                "TargetName": CREDENTIAL_TARGET,
                "UserName": CREDENTIAL_USER,
                "CredentialBlob": cleaned,
                "Comment": "SHRADDHA AI - Gemini API key",
                "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
            },
            0,
        )
    except Exception as exc:
        raise KeyStoreError(f"could not store the key: {exc}") from exc


def delete_credential() -> bool:
    """Remove the stored key. Returns True when something was deleted."""
    available, _reason = credential_support()
    if not available:
        return False
    import win32cred

    try:
        win32cred.CredDelete(CREDENTIAL_TARGET, win32cred.CRED_TYPE_GENERIC, 0)
        return True
    except Exception:
        return False


def resolve_api_key(
    environ: Mapping[str, str] | None = None,
    credential_reader: Callable[[], str | None] | None = None,
    extra_env: str | None = None,
) -> tuple[str | None, str]:
    """Return ``(key, source)`` following the documented precedence."""
    env = os.environ if environ is None else environ
    reader = read_credential if credential_reader is None else credential_reader

    for name in (extra_env, PRIMARY_ENV, SECONDARY_ENV):
        if not name:
            continue
        value = _clean(env.get(name))
        if value:
            return value, f"env:{name}"

    try:
        stored = reader()
    except Exception as exc:  # a broken store must not break startup
        log.warning("credential store failed: %s", exc)
        stored = None
    if _clean(stored):
        return _clean(stored), SOURCE_CREDENTIAL
    return None, SOURCE_NONE


__all__ = [
    "CREDENTIAL_TARGET",
    "PRIMARY_ENV",
    "SECONDARY_ENV",
    "SOURCE_CREDENTIAL",
    "SOURCE_NONE",
    "KeyStoreError",
    "credential_support",
    "delete_credential",
    "mask_key",
    "read_credential",
    "resolve_api_key",
    "write_credential",
]
