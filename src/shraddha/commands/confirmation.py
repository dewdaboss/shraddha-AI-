"""The yes/no gate that stands between a sensitive command and the operating system.

A single ambiguous syllable should never shut a computer down, so an approved command
must be approved *by its own utterance*: the gate keeps one pending command, matches the
next thing the user says against explicit yes/no vocabularies, and clears itself either
way. Anything unclear keeps the command pending rather than guessing.
"""

from __future__ import annotations

from enum import StrEnum

from shraddha.commands.router import Command

YES_WORDS = (
    "हाँ",
    "हां",
    "हा",
    "जी हाँ",
    "जी हां",
    "ठीक है",
    "ठीक",
    "करो",
    "कर दो",
    "हो जाए",
    "haan",
    "han",
    "ha",
    "yes",
    "yeah",
    "yep",
    "ok",
    "okay",
    "sure",
    "theek",
    "theek hai",
    "karo",
    "kar do",
)
NO_WORDS = (
    "नहीं",
    "नही",
    "ना",
    "मत करो",
    "रहने दो",
    "कैंसिल",
    "केंसल",
    "बंद करो बात",
    "nahi",
    "nahin",
    "na",
    "no",
    "nope",
    "cancel",
    "stop",
    "mat karo",
    "rehne do",
)


class ConfirmationOutcome(StrEnum):
    APPROVED = "approved"
    DECLINED = "declined"
    UNCLEAR = "unclear"
    NONE = "none"


class ConfirmationGate:
    """Holds at most one command awaiting a yes/no answer."""

    def __init__(self) -> None:
        self._pending: Command | None = None

    @property
    def pending(self) -> Command | None:
        return self._pending

    @property
    def is_waiting(self) -> bool:
        return self._pending is not None

    def request(self, command: Command) -> Command:
        """Remember a command that needs confirmation and return it."""
        self._pending = command
        return command

    def resolve(self, text: str) -> tuple[ConfirmationOutcome, Command | None]:
        """Interpret a reply. Approves at most once, then forgets the command."""
        if self._pending is None:
            return ConfirmationOutcome.NONE, None

        answer = self._normalise(text)
        if not answer:
            return ConfirmationOutcome.UNCLEAR, None

        if self._matches(answer, NO_WORDS):
            self._pending = None
            return ConfirmationOutcome.DECLINED, None

        if self._matches(answer, YES_WORDS):
            approved = self._pending
            self._pending = None
            return ConfirmationOutcome.APPROVED, approved

        return ConfirmationOutcome.UNCLEAR, None

    def clear(self) -> None:
        self._pending = None

    # ------------------------------------------------------------------ private
    @staticmethod
    def _normalise(text: str) -> str:
        cleaned = "".join(
            " " if char in "।॥,.!?;:\"'()[]{}" else char for char in (text or "").casefold()
        )
        return " ".join(cleaned.split())

    @staticmethod
    def _matches(answer: str, vocabulary: tuple[str, ...]) -> bool:
        # Exact first: "नहीं" must not be swallowed by a yes-word that contains it.
        if answer in vocabulary:
            return True
        words = answer.split()
        return any(word in vocabulary for word in words)
