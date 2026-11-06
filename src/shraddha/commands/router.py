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

import re
from dataclasses import dataclass, field

from shraddha.commands.apps import FOLDER_ALIASES, find_app, find_folder, normalise_name
from shraddha.commands.timer import hindi_duration
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

# --- Phase 4: everyday skills ------------------------------------------------
INTENT_TIMER_SET = "timer.set"
INTENT_TIMER_CANCEL = "timer.cancel"
INTENT_TIMER_STATUS = "timer.status"
INTENT_NOTE_ADD = "note.add"
INTENT_NOTE_READ = "note.read"
INTENT_NOTE_CLEAR = "note.clear"
INTENT_CLIPBOARD_COPY = "clipboard.copy"
INTENT_CLIPBOARD_READ = "clipboard.read"
INTENT_VOLUME = "volume.control"
INTENT_WINDOW = "window.control"
INTENT_FILE_SEARCH = "file.search"

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
        """True when executing this command changes something outside the chat."""
        return self.intent in {
            INTENT_APP_OPEN,
            INTENT_WEB_OPEN,
            INTENT_FOLDER_OPEN,
            INTENT_POWER,
            INTENT_TIMER_SET,
            INTENT_TIMER_CANCEL,
            INTENT_TIMER_STATUS,
            INTENT_NOTE_ADD,
            INTENT_NOTE_READ,
            INTENT_NOTE_CLEAR,
            INTENT_CLIPBOARD_COPY,
            INTENT_CLIPBOARD_READ,
            INTENT_VOLUME,
            INTENT_WINDOW,
            INTENT_FILE_SEARCH,
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

        # "म्यूट" means the microphone - unless the sentence is about the speakers.
        if not has_volume_context(cleaned) and (
            contains_stop_phrase(raw) or contains_stop_phrase(cleaned)
        ):
            return Command(INTENT_VOICE_STOP, "ठीक है, मैं सुनना बंद कर रही हूँ।", raw=raw)

        if _contains(cleaned, _VOICE_SWITCH):
            return Command(INTENT_VOICE_SWITCH, "", raw=raw)

        # Phase 4 skills run before date/time ("टाइमर" contains "टाइम") and before the
        # open-verb routing (so "note likho …" is not mistaken for "notepad kholo").
        skill = route_skill(cleaned, raw)
        if skill is not None:
            return skill

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
            elif cleaned.startswith(f"{verb} ") and (best is None or best > 0):
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


# ---------------------------------------------------------------------------
# Phase 4 - everyday skills: timer, notes, clipboard, volume, windows, search.
#
# All of it is pure text parsing. Nothing here touches the OS; the executor does that,
# and only after re-validating what came out of these functions.
# ---------------------------------------------------------------------------

#: Words that make "mute"/"आवाज़" mean the speakers rather than the microphone.
_VOLUME_CONTEXT = ("volume", "वॉल्यूम", "awaaz", "aawaz", "आवाज़", "आवाज", "speaker", "स्पीकर", "साउंड")

_TIMER_WORDS = ("timer", "टाइमर", "alarm", "अलार्म", "reminder", "रिमाइंडर")
_TIMER_CANCEL_WORDS = ("cancel", "band", "बंद", "रद्द", "hatao", "हटाओ", "off", "बन्द")
_TIMER_STATUS_WORDS = ("kitna", "कितना", "remaining", "बाकी", "status", "chal raha", "चल रहा")

_OPEN_VERB_MARKERS = ("kholo", "khol", "खोलो", "खोल", "open", "launch", "चालू", "शुरू")

_NOTE_WORDS = ("note", "नोट", "notes", "नोट्स")
_NOTE_ADD_VERBS = (
    "likho",
    "likh do",
    "likh",
    "likhna",
    "banao",
    "bana do",
    "banado",
    "save",
    "add",
    "लिखो",
    "लिख",
    "बनाओ",
    "बना दो",
    "सेव",
    "जोड़ो",
)
_NOTE_READ_VERBS = (
    "padho",
    "padh",
    "sunao",
    "batao",
    "bata do",
    "dikhao",
    "read",
    "show",
    "पढ़ो",
    "पढ",
    "सुनाओ",
    "बताओ",
    "दिखाओ",
)
_NOTE_CLEAR_VERBS = ("clear", "delete", "hatao", "mita", "साफ", "हटाओ", "मिटा", "khaali")

_CLIPBOARD_WORDS = ("clipboard", "क्लिपबोर्ड")
_COPY_VERBS = ("copy", "kopi", "कॉपी", "कापी", "क्लिपबोर्ड", "clipboard")
_CLIPBOARD_READ_WORDS = ("kya hai", "padho", "batao", "dikhao", "read", "show", "क्या है", "पढ़ो", "बताओ")
#: Pronouns that carry no content: "ye copy karo" needs a follow-up question.
_EMPTY_TARGETS = frozenset({"", "ye", "yeh", "this", "ise", "इसे", "यह", "isko", "इसको", "it", "text"})

_VOLUME_WORDS = ("volume", "वॉल्यूम", "आवाज़", "आवाज", "awaaz", "aawaz", "speaker", "स्पीकर")
_VOLUME_MUTE = ("mute", "म्यूट", "silent", "साइलेंट", "band karo", "बंद करो", "बंद")
_VOLUME_UP = ("badhao", "badha do", "badha", "up", "बढ़ाओ", "बढ़ा", "तेज", "तेज़", "increase")
_VOLUME_DOWN = ("kam karo", "kam", "ghatao", "ghata", "down", "कम", "घटाओ", "घटा", "धीमा", "decrease")

_WINDOW_WORDS = ("window", "विंडो")
_WINDOW_MINIMIZE = ("minimize", "minimise", "min", "chhota", "chota", "छोटा", "mini")
_WINDOW_CLOSE = ("close", "band", "बंद", "hatao", "हटाओ", "बन्द")

_SEARCH_VERBS = ("dhundo", "dhoondo", "dhund", "ढूंढो", "ढूँढो", "ढूंढ", "khojo", "खोजो", "search", "find")
_SEARCH_FILLERS = frozenset(
    {"file", "files", "फाइल", "फ़ाइल", "फाइलें", "mein", "me", "में", "मे", "ka", "ki", "ke", "को", "for", "the"}
)

_NUMBER_WORDS = {
    "ek": 1,
    "एक": 1,
    "do": 2,
    "दो": 2,
    "teen": 3,
    "तीन": 3,
    "char": 4,
    "chaar": 4,
    "चार": 4,
    "paanch": 5,
    "panch": 5,
    "पांच": 5,
    "पाँच": 5,
    "chhah": 6,
    "che": 6,
    "छह": 6,
    "chhe": 6,
    "saat": 7,
    "सात": 7,
    "aath": 8,
    "आठ": 8,
    "nau": 9,
    "नौ": 9,
    "das": 10,
    "दस": 10,
    "aadha": 0.5,
    "आधा": 0.5,
    "आधे": 0.5,
}

_UNIT_SECONDS = {
    "second": 1,
    "seconds": 1,
    "sec": 1,
    "secs": 1,
    "सेकंड": 1,
    "सेकण्ड": 1,
    "minute": 60,
    "minutes": 60,
    "min": 60,
    "mins": 60,
    "मिनट": 60,
    "hour": 3_600,
    "hours": 3_600,
    "hr": 3_600,
    "घंटा": 3_600,
    "घंटे": 3_600,
    "ghanta": 3_600,
    "ghante": 3_600,
}

_DURATION_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>seconds?|secs?|minutes?|mins?|hours?|hrs?|hr|ghanta|ghante|सेकंड|सेकण्ड|मिनट|घंटे|घंटा)"
)

#: Timers outside this range are almost certainly a misrecognition.
MIN_TIMER_S = 5
MAX_TIMER_S = 24 * 3_600


def has_volume_context(cleaned: str) -> bool:
    """True when the sentence talks about the speakers, not the microphone."""
    return _contains(cleaned, _VOLUME_CONTEXT)


def _padded(text: str) -> str:
    return f" {text} "


#: Words that carry no content when they follow the verb: "copy *karo* baithak 5 baje".
_CONNECTORS = (
    "kar do",
    "kardo",
    "karo",
    "kar",
    "कर दो",
    "करो",
    "कर",
    "ko",
    "को",
    "mein",
    "में",
    "me",
    "मे",
    "daalo",
    "daal do",
    "डालो",
    "डाल दो",
)


def _text_after(cleaned: str, verbs: tuple[str, ...]) -> str:
    """Everything after the first whole-word match of any verb (``""`` when none)."""
    padded = _padded(cleaned)
    best: int | None = None
    best_len = 0
    for verb in verbs:
        index = padded.find(f" {verb} ")
        if index >= 0 and (best is None or index < best):
            best, best_len = index, len(verb)
    if best is None:
        return ""
    return _strip_connectors(padded[best + 1 + best_len :].strip())


def _strip_connectors(text: str) -> str:
    changed = True
    while changed and text:
        changed = False
        for connector in _CONNECTORS:
            if text == connector:
                return ""
            if text.startswith(f"{connector} "):
                text = text[len(connector) + 1 :].strip()
                changed = True
                break
    return text


def _words_to_digits(cleaned: str) -> str:
    tokens = [_NUMBER_WORDS.get(token, token) for token in cleaned.split()]
    return " ".join(str(token) for token in tokens)


def duration_seconds(cleaned: str) -> int | None:
    """Total seconds in "5 minute", "1 ghanta 30 min" or "आधे घंटे"; ``None`` if absent."""
    total = 0.0
    for match in _DURATION_RE.finditer(_words_to_digits(cleaned)):
        unit = _UNIT_SECONDS.get(match.group("unit"))
        if unit is None:  # pragma: no cover - regex only lists known units
            continue
        total += float(match.group("value")) * unit
    if total <= 0:
        return None
    return round(total)


def parse_timer(cleaned: str) -> Command | None:
    if not _contains(cleaned, _TIMER_WORDS):
        return None
    if _contains(cleaned, _TIMER_CANCEL_WORDS):
        return Command(INTENT_TIMER_CANCEL, "ठीक है, टाइमर रद्द कर रही हूँ।")
    if _contains(cleaned, _TIMER_STATUS_WORDS) and duration_seconds(cleaned) is None:
        return Command(INTENT_TIMER_STATUS, "")
    seconds = duration_seconds(cleaned)
    if seconds is None:
        return Command(INTENT_UNKNOWN, "कितने मिनट का टाइमर लगाना है? जैसे - \"5 मिनट का टाइमर\".")
    if not MIN_TIMER_S <= seconds <= MAX_TIMER_S:
        return Command(
            INTENT_UNKNOWN,
            f"टाइमर {MIN_TIMER_S} सेकंड से 24 घंटे के बीच होना चाहिए।",
        )
    label = hindi_duration(seconds)
    return Command(
        INTENT_TIMER_SET,
        f"{label} का टाइमर लगा रही हूँ।",
        args={"seconds": str(seconds)},
    )


def parse_note(cleaned: str) -> Command | None:
    if not _contains(cleaned, _NOTE_WORDS):
        return None
    if _contains(cleaned, _OPEN_VERB_MARKERS) and not _contains(cleaned, _NOTE_ADD_VERBS):
        return None  # "notepad kholo" is an app command, not a note command
    if _contains(cleaned, _NOTE_CLEAR_VERBS):
        return Command(
            INTENT_NOTE_CLEAR,
            "क्या सच में सारे नोट्स हटा दूँ? 'हाँ' या 'नहीं' कहिए।",
            needs_confirmation=True,
        )
    if _contains(cleaned, _NOTE_READ_VERBS):
        return Command(INTENT_NOTE_READ, "")
    text = _text_after(cleaned, _NOTE_ADD_VERBS)
    if not text:
        if _contains(cleaned, _NOTE_ADD_VERBS):
            return Command(INTENT_UNKNOWN, "क्या नोट लिखना है? जैसे - \"नोट लिखो दूध लाना है\".")
        return None
    return Command(INTENT_NOTE_ADD, "नोट लिख लिया।", args={"text": text})


def parse_clipboard(cleaned: str) -> Command | None:
    if not _contains(cleaned, _CLIPBOARD_WORDS) and not _contains(cleaned, _COPY_VERBS):
        return None
    if _contains(cleaned, _CLIPBOARD_WORDS) and _contains(cleaned, _CLIPBOARD_READ_WORDS):
        return Command(INTENT_CLIPBOARD_READ, "")
    text = _text_after(cleaned, _COPY_VERBS)
    if text.lower() in _EMPTY_TARGETS:
        if _contains(cleaned, _COPY_VERBS):
            return Command(
                INTENT_UNKNOWN,
                "क्या कॉपी करना है? जैसे - \"कॉपी करो बैठक 5 बजे\".",
            )
        return None
    return Command(INTENT_CLIPBOARD_COPY, "क्लिपबोर्ड पर कॉपी कर दिया।", args={"text": text})


def parse_volume(cleaned: str) -> Command | None:
    if not _contains(cleaned, _VOLUME_WORDS):
        return None
    if _contains(cleaned, _VOLUME_MUTE):
        return Command(INTENT_VOLUME, "आवाज़ म्यूट कर दी।", args={"action": "mute"})
    level = re.search(r"(?<!\d)(\d{1,3})(?!\d)", cleaned)
    if level is not None:
        value = int(level.group(1))
        if 0 <= value <= 100:
            return Command(INTENT_VOLUME, "", args={"action": "set", "level": str(value)})
    if _contains(cleaned, _VOLUME_UP):
        return Command(INTENT_VOLUME, "आवाज़ बढ़ा रही हूँ।", args={"action": "up"})
    if _contains(cleaned, _VOLUME_DOWN):
        return Command(INTENT_VOLUME, "आवाज़ कम कर रही हूँ।", args={"action": "down"})
    return None


def parse_window(cleaned: str) -> Command | None:
    if not _contains(cleaned, _WINDOW_WORDS):
        return None
    if _contains(cleaned, _WINDOW_CLOSE):
        return Command(
            INTENT_WINDOW,
            "क्या यह विंडो बंद कर दूँ? 'हाँ' या 'नहीं' कहिए।",
            args={"action": "close"},
            needs_confirmation=True,
        )
    if _contains(cleaned, _WINDOW_MINIMIZE):
        return Command(INTENT_WINDOW, "विंडो छोटा कर रही हूँ।", args={"action": "minimize"})
    return None


def parse_search(cleaned: str) -> Command | None:
    if not _contains(cleaned, _SEARCH_VERBS):
        return None
    folder = _search_folder(cleaned)
    tokens = [
        token
        for token in cleaned.split()
        if token not in _SEARCH_VERBS
        and token not in _SEARCH_FILLERS
        and not _is_folder_token(token)
    ]
    query = " ".join(tokens).strip()
    if not query:
        return Command(
            INTENT_UNKNOWN,
            "क्या ढूँढना है? जैसे - \"documents में बजट फाइल ढूँढो\".",
        )
    args = {"query": query}
    if folder:
        args["folder"] = folder
    return Command(INTENT_FILE_SEARCH, "", args=args)


def _search_folder(cleaned: str) -> str | None:
    for key, aliases in FOLDER_ALIASES.items():
        if any(alias in cleaned for alias in aliases):
            return key
    return None


def _is_folder_token(token: str) -> bool:
    return any(token in aliases for aliases in FOLDER_ALIASES.values())


def route_skill(cleaned: str, raw: str) -> Command | None:
    """Try every Phase 4 skill in priority order; ``None`` when none of them match."""
    for parser in (parse_timer, parse_note, parse_clipboard, parse_volume, parse_window, parse_search):
        command = parser(cleaned)
        if command is not None:
            return Command(
                command.intent,
                command.spoken,
                args=dict(command.args),
                needs_confirmation=command.needs_confirmation,
                raw=raw,
            )
    return None
