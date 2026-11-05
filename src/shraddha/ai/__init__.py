"""Optional cloud intelligence for SHRADDHA AI (Phase 3).

Public surface::

    from shraddha.ai import make_service, consent_intent

    service = make_service(config.llm)
    for event in service.ask("भारत की राजधानी क्या है?"):
        ...

Nothing in this package can act on the computer: it has no access to
:mod:`shraddha.commands` or :mod:`subprocess`, and a test keeps it that way.
"""

from __future__ import annotations

from shraddha.ai.base import (
    CLOUD_PROVIDERS,
    KNOWN_PROVIDERS,
    AiError,
    AiEvent,
    ChatMessage,
    LlmProvider,
    ProviderInfo,
    collect_stream,
    module_available,
)
from shraddha.ai.gemini import DEPENDENCY as GEMINI_DEPENDENCY
from shraddha.ai.gemini import GeminiProvider
from shraddha.ai.keys import (
    CREDENTIAL_TARGET,
    PRIMARY_ENV,
    SECONDARY_ENV,
    credential_support,
    delete_credential,
    mask_key,
    resolve_api_key,
    write_credential,
)
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
    make_service,
    seed_history,
)
from shraddha.config import LlmConfig

__version__ = "3.0.0"

#: Provider implementations that are actually importable today.
AVAILABLE_PROVIDERS = tuple(name for name in CLOUD_PROVIDERS if name == "gemini")


def provider_status(llm: LlmConfig) -> ProviderInfo:
    """Cheap, no-network description of the configured provider."""
    provider = create_provider(llm)
    if provider is None:
        return ProviderInfo(name=llm.provider, model=llm.model, ready=False, message="कोई provider नहीं")
    try:
        ready, reason = provider.availability()
        return ProviderInfo(name=provider.name, model=llm.model, ready=ready, message=reason)
    finally:
        provider.close()


def key_report(llm: LlmConfig) -> dict[str, object]:
    """Non-secret key facts for ``--ai-status`` and the doctor report."""
    key, source = resolve_api_key(extra_env=llm.api_key_env or None)
    supported, reason = credential_support()
    return {
        "present": bool(key),
        "masked": mask_key(key),
        "source": source,
        "credential_store": supported,
        "credential_reason": reason,
    }


__all__ = [
    "AVAILABLE_PROVIDERS",
    "CLOUD_PROVIDERS",
    "CREDENTIAL_TARGET",
    "GEMINI_DEPENDENCY",
    "KNOWN_PROVIDERS",
    "PRIMARY_ENV",
    "SECONDARY_ENV",
    "STATUS_CONSENT",
    "STATUS_NO_KEY",
    "STATUS_NO_PROVIDER",
    "STATUS_NO_SDK",
    "STATUS_OFF",
    "STATUS_READY",
    "AiError",
    "AiEvent",
    "AiService",
    "ChatMessage",
    "GeminiProvider",
    "LlmProvider",
    "ProviderInfo",
    "__version__",
    "collect_stream",
    "consent_intent",
    "create_provider",
    "credential_support",
    "delete_credential",
    "key_report",
    "make_service",
    "mask_key",
    "module_available",
    "provider_status",
    "resolve_api_key",
    "seed_history",
    "write_credential",
]
