"""The "thinking" layer: optional large-language-model answers.

Two rules shape this package:

1. **It is optional.** A fresh install has ``llm.provider = "none"``; nothing here is
   imported, no socket is opened, and the assistant answers from its local rule engine.
2. **It never acts.** ``shraddha.ai`` may produce *text* only. It cannot import
   :mod:`subprocess` or :mod:`shraddha.commands.actions` (a test enforces this), so a model
   can never open an application, run a command, or touch the file system.

Cloud providers additionally require a key *and* explicit consent; see
:mod:`shraddha.ai.service` for the gate and :mod:`shraddha.ai.keys` for key handling.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from shraddha.logging_setup import get_logger

log = get_logger("ai")

#: Providers that exist today. ``local`` is the Phase 6 llama.cpp provider.
CLOUD_PROVIDERS = ("gemini",)
KNOWN_PROVIDERS = ("none", "gemini", "local")


class AiError(RuntimeError):
    """A failed AI call, with a code and a sentence the user can act on."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "ai_error",
        hint: str = "",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.hint = hint
        self.code = code
        self.retryable = retryable

    def user_message(self) -> str:
        return f"{self}\n({self.hint})" if self.hint else str(self)


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One turn of conversation, in the provider's neutral shape."""

    role: str  # "user" | "assistant"
    text: str

    @property
    def is_user(self) -> bool:
        return self.role == "user"


@dataclass(frozen=True, slots=True)
class AiEvent:
    """What the UI receives while an answer is produced."""

    kind: str  # state | partial | final | error
    text: str = ""
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    """Doctor/CLI view of a provider."""

    name: str
    model: str = ""
    ready: bool = False
    message: str = ""


@runtime_checkable
class LlmProvider(Protocol):
    """Minimal surface every provider must implement."""

    name: str
    model: str

    def availability(self) -> tuple[bool, str]:
        """``(ready, reason)`` - cheap, no network call."""

    def stream(self, messages: list[ChatMessage], system: str | None = None) -> Iterator[str]:
        """Yield text chunks. Raises :class:`AiError`."""

    def close(self) -> None:
        """Release the client."""


def module_available(module_name: str) -> bool:
    """True when a module can be imported, without importing it."""
    import importlib.util

    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def collect_stream(provider: LlmProvider, messages: list[ChatMessage], system: str | None = None) -> str:
    """Helper for callers that do not need partial results."""
    return "".join(provider.stream(messages, system)).strip()


#: Injected in tests so no real client is ever built.
ClientFactory = Callable[[str], object]

__all__ = [
    "CLOUD_PROVIDERS",
    "KNOWN_PROVIDERS",
    "AiError",
    "AiEvent",
    "ChatMessage",
    "ClientFactory",
    "LlmProvider",
    "ProviderInfo",
    "collect_stream",
    "module_available",
]
