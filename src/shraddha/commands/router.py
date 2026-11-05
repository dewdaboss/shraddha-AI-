"""Hindi/Hinglish command router - text in, validated intent out.

This module is pure: no filesystem writes, no processes, no network. It converts what the
user *said* into what they *meant* and refuses to guess beyond the catalogs in
:mod:`shraddha.commands.apps`. Everything it emits is re-validated by
:class:`~shraddha.commands.actions.ActionExecutor` before the OS sees it.

Ordering matters and is tested:

1. "सुनना बंद करो"      -> stop listening (before "बंद करो" can mean shutdown)
2. voice switching      -> change the spoken voice
3. date / time          -> answered from the system clock, never executed
4. power actions        -> sensitive, need confirmation, disabled by default
5. "X खोलो"             -> allowlisted app / folder / URL
6. anything else        -> ``unknown`` so the chat layer can answer it
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shraddha.commands.apps import find_app, find_folder, normalise_name
from shraddha.speech.wake import WakeWordMatcher, contains_stop_phrase

INTENT_APP_OPEN = "app.open"
INTENT_WEB_OPEN = "web.open"
INTENT_FOLDER_OPEN = "folder.open"
INTENT_INFO_TIME = "info.time"
INTENT_INFO_DATE = "info.date"
INTENT_VOICE_STOP = "voice.stop"
INTENT_VOICE_SWITCH = "voice.switch"
INTENT_POWER = "system.power"
INTENT_UNKNOWN = "unknown"

_OPEN_VERBS = (
    "kholo",
    "khol",
    "kholiye",
    "kholie",
    "kholna",
    "kholo na",
    "open",
    "launch",
    "start",
    "run",
    "चालू",
    "खोलो",
    "खोल",
    "खोलिए",
    "खोलिये",
    "खोलना",
    "शुरू",
    "ओपन",
    "चलाओ",
    "चला",
    "on",
)
_DATE_WORDS = ("तारीख", "तारीख़", "दिनांक", "date", "tarikh", "tareekh", "कौन सा दिन")
_TIME_WORDS = ("समय", "टाइम", "बजे", "time", "samay", "baje")
_VOICE_SWITCH = (
    "आवाज बदलो",
    "आवाज़ बदलो",
    "आवाज बदल",
    "आवाज़ बदल",
    "voice change",
    "change voice",
    "switch voice",
    "आवाज़ चुनो",
    "आवाज चुनो",
    "next voice",
    "दूसरी आवाज",
)
_POWER_WORDS = (
    "शटडाउन",
    "shutdown",
    "shut down",
    "शट डाउन",
    "रीस्टार्ट",
    "restart",
    "reboot",
    "स्लीप",
    "sleep",
    "लॉक",
    "lock",
    "कंप्यूटर बंद",
    "computer band",
)
_POWER_GUARD = ("मत", "ना", "नहीं", "nahi", "don't", "dont", "do not")

UNKNOWN_TARGET_HINT = (
    "मुझे यह नहीं पता कि इसे कैसे खोलना है। मैं केवल तय सूची में से खोल सकती हूँ - "
    "जैसे Chrome, Edge, Notepad, Calculator, Files, Settings, VS Code या Downloads फोल्डर।"
)


@dataclass(frozen=True, slots=True)
class Command:
    """A validated intent plus the Hindi sentence the assistant should say."""

    intent: str
    spoken: str = ""
    args: dict[str, str] = field(default_factory=dict)
    needs_confirmation: bool = False
    raw: str = ""

    @property
    def target(self) -> str:
        return self.args.get("target", "")

    @property
    def is_actionable(self) -> bool:
        return self.intent in {
            INTENT_APP_OPEN,
            INTENT_WEB_OPEN,
            INTENT_FOLDER_OPEN,
            INTENT_POWER,
        }


def _contains(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


class CommandRouter:
    """Turns a transcript into a :class:`Command`."""

    def __init__(
        self,
        allow_power_actions: bool = False,
        enabled: bool = True,
        wake_phrases: tuple[str, ...] | list[str] | None = None,
    ) -> None:
        self.allow_power_actions = allow_power_actions
        self.enabled = enabled
        #: A transcript often starts with the assistant's own name.
        self._matcher = WakeWordMatcher(wake_phrases)

    def route(self, text: str) -> Command:
        raw = (text or "").strip()
        # "श्रद्धा, Chrome खोलो" -> "Chrome खोलो": drop the name if it prefixes a command.
        match = self._matcher.detect(raw)
        if match.matched and match.has_command:
            raw = match.command
        cleaned = normalise_name(raw)
        if not cleaned:
            return Command(INTENT_UNKNOWN, "कुछ सुनाई नहीं दिया।", raw=raw)

        if not self.enabled:
            return Command(
                INTENT_UNKNOWN,
                "आवाज़ से आदेश देना सेटिंग में बंद है।",
                raw=raw,
            )

        if contains_stop_phrase(raw) or contains_stop_phrase(cleaned):
            return Command(INTENT_VOICE_STOP, "ठीक है, मैं सुनना बंद कर रही हूँ।", raw=raw)

        if _contains(cleaned, _VOICE_SWITCH):
            return Command(INTENT_VOICE_SWITCH, "", raw=raw)

        if not _contains(cleaned, _POWER_GUARD) and _contains(cleaned, _POWER_WORDS):
            spoken = (
                "क्या आप सच में कंप्यूटर बंद करना चाहते हैं? 'हाँ' या 'नहीं' कहिए।"
                if self.allow_power_actions
                else "सुरक्षा के लिए कंप्यूटर बंद करना अभी बंद रखा गया है।"
            )
            return Command(
                INTENT_POWER,
                spoken,
                args={"action": self._power_action(cleaned)},
                needs_confirmation=self.allow_power_actions,
                raw=raw,
            )

        if _contains(cleaned, _DATE_WORDS):
            return Command(INTENT_INFO_DATE, "", raw=raw)
        if _contains(cleaned, _TIME_WORDS):
            return Command(INTENT_INFO_TIME, "", raw=raw)

        opened = self._route_open(cleaned, raw)
        if opened is not None:
            return opened

        return Command(INTENT_UNKNOWN, "", raw=raw)

    # ------------------------------------------------------------------ private
    def _route_open(self, cleaned: str, raw: str) -> Command | None:
        verb_index = self._verb_index(cleaned)
        if verb_index is None:
            return None

        before = cleaned[:verb_index].strip()
        after = cleaned[verb_index:].split(" ", 1)
        after = after[1].strip() if len(after) > 1 else ""
        phrase = before or after

        if not phrase:
            return Command(INTENT_UNKNOWN, "क्या खोलना है?", raw=raw)

        app = find_app(phrase)
        if app is not None:
            if app.is_web and app.url:
                return Command(
                    INTENT_WEB_OPEN,
                    f"{app.label} खोल रही हूँ।",
                    args={"target": app.key, "url": app.url},
                    raw=raw,
                )
            return Command(
                INTENT_APP_OPEN,
                f"{app.label} खोल रही हूँ।",
                args={"target": app.key},
                raw=raw,
            )

        folder = find_folder(phrase)
        if folder is not None:
            key, path = folder
            return Command(
                INTENT_FOLDER_OPEN,
                "आपका फोल्डर खोल रही हूँ।",
                args={"target": key, "path": str(path)},
                raw=raw,
            )

        return Command(INTENT_UNKNOWN, UNKNOWN_TARGET_HINT, raw=raw)

    @staticmethod
    def _verb_index(cleaned: str) -> int | None:
        """Character offset of the first open-verb, or ``None``."""
        best: int | None = None
        for verb in _OPEN_VERBS:
            index = cleaned.find(f" {verb}")
            if index >= 0:
                candidate = index + 1
                if best is None or candidate < best:
                    best = candidate
            elif cleaned.startswith(f"{verb} "):
                if best is None or best > 0:
                    best = 0
        return best

    @staticmethod
    def _power_action(cleaned: str) -> str:
        if any(word in cleaned for word in ("restart", "reboot", "रीस्टार्ट")):
            return "restart"
        if any(word in cleaned for word in ("sleep", "स्लीप")):
            return "sleep"
        if any(word in cleaned for word in ("lock", "लॉक")):
            return "lock"
        return "shutdown"
