"""The assistant's reply engine - deliberately tiny in Phase 1.

This is **not** the AI. It is a deterministic, offline responder that makes the
interface usable and testable before the speech and language layers exist:

* time / date / help / identity / greeting / thanks - real answers, built locally;
* everything else - an honest "I am not connected to a language model yet".

Phase 4 replaces the keyword matcher with a proper Hindi/Hinglish grammar, and Phase 6
adds the optional local LLM. Both slot in behind :meth:`Assistant.respond`, so the UI
never has to change.

No network. No paid API. No model. This module must stay importable in microseconds.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

#: Reply origins, mirrored by the chat view's bubble styling.
KIND_ASSISTANT = "assistant"
KIND_USER = "user"
KIND_SYSTEM = "system"

#: Devanagari and Roman spellings of the same keyword, so Hinglish input works today.
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "date": ("तारीख", "तारीख़", "दिनांक", "कौन सी तारीख", "date", "tarikh", "tareekh", "aaj kaun"),
    "time": ("समय", "टाइम", "बजे", "time", "samay", "kitne baje", "baje"),
    "help": ("मदद", "सहायता", "help", "madad", "sahayata", "kya kar sakti", "क्या कर सकती"),
    "identity": ("तुम कौन", "आप कौन", "who are you", "kaun ho", "tum kaun", "तुम्हारा नाम"),
    "thanks": ("धन्यवाद", "शुक्रिया", "thanks", "thank you", "dhanyavad", "shukriya"),
    "greeting": ("नमस्ते", "नमस्कार", "हैलो", "हाय", "hello", "hi", "hey", "namaste", "namaskar"),
}

#: Checked in order: the most specific intents first, greetings last (they are the
#: most likely to appear as a substring of something else).
_PRIORITY = ("date", "time", "help", "identity", "thanks", "greeting")

_WEEKDAYS = ("सोमवार", "मंगलवार", "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "रविवार")
_MONTHS = (
    "जनवरी",
    "फ़रवरी",
    "मार्च",
    "अप्रैल",
    "मई",
    "जून",
    "जुलाई",
    "अगस्त",
    "सितंबर",
    "अक्टूबर",
    "नवंबर",
    "दिसंबर",
)

FALLBACK_TEXT = (
    "माफ़ कीजिए, अभी मैं भाषा-मॉडल से नहीं जुड़ी हूँ, इसलिए इस सवाल का जवाब नहीं दे सकती। "
    "स्थानीय AI Phase 6 में जुड़ेगा (पूरी तरह ऑफ़लाइन, कोई शुल्क नहीं)। "
    "'मदद' लिखिए तो मैं बता दूँगी कि अभी क्या-क्या कर सकती हूँ।\n\n"
    "(I am not connected to a language model yet, so I cannot answer that. "
    "Type 'help' to see what works today.)"
)

HELP_TEXT = (
    "अभी मैं ये काम कर सकती हूँ:\n"
    '• समय बताना - "समय क्या है?"\n'
    '• तारीख़ बताना - "आज कौन सी तारीख़ है?"\n'
    '• ऐप खोलना - "Chrome खोलो", "notepad kholo"\n'
    '• फोल्डर खोलना - "मेरी डाउनलोड फाइल खोलो", "documents kholo"\n'
    '• अपने बारे में बताना - "तुम कौन हो?"\n\n'
    "आवाज़ से भी बोल सकती हूँ: माइक दबाइए, या 'श्रद्धा' कहकर बुलाइए। "
    'सुनना बंद करने के लिए कहिए - "मेरी बात सुनना बंद करो"।\n\n'
    "अगले चरण: आवाज़ की बारीकियाँ (Phase 3), और ज़्यादा आदेश (Phase 4), "
    "और स्थानीय AI (Phase 6)।"
)

IDENTITY_TEXT = (
    "मैं श्रद्धा हूँ - एक स्थानीय, ऑफ़लाइन हिन्दी सहायक। "
    "मेरा सारा काम आपके कंप्यूटर पर ही होता है: कोई क्लाउड नहीं, कोई API कुंजी नहीं, "
    "और आपकी आवाज़ कभी बाहर नहीं जाती।"
)


@dataclass(frozen=True, slots=True)
class Reply:
    """One turn of assistant output."""

    text: str
    intent: str = "fallback"
    kind: str = KIND_ASSISTANT

    @property
    def is_fallback(self) -> bool:
        return self.intent == "fallback"


def normalise(text: str) -> str:
    """Fold input for matching: case, nukta variants, punctuation, spacing.

    ``तारीख़`` and ``तारीख`` are the same word to a person; they must be the same word
    to the matcher. Only nukta (U+093C) and zero-width joiners are removed - never the
    virama, which changes the word.
    """
    lowered = text.casefold()
    for char in ("\u093c", "\u200c", "\u200d"):
        lowered = lowered.replace(char, "")
    cleaned = "".join(" " if char in "?.,!;:\"'()[]{}।॥" else char for char in lowered)
    return " ".join(cleaned.split())


class Assistant:
    """Deterministic responder. Inject ``now`` for reproducible tests."""

    def __init__(self, language: str = "hi", now: Callable[[], datetime] | None = None) -> None:
        self.language = language
        self._now = now or datetime.now

    def respond(self, text: str) -> Reply:
        """Answer ``text`` (Hindi, Hinglish or English keywords). Never raises."""
        cleaned = normalise(text or "")
        if not cleaned:
            return Reply("कुछ लिखिए या बोलिए, मैं सुन रही हूँ।", intent="empty")

        intent = self.match_intent(cleaned)
        return Reply(self._answer(intent), intent=intent)

    @staticmethod
    def match_intent(cleaned: str) -> str:
        """Return the first matching intent, or ``"fallback"``."""
        for intent in _PRIORITY:
            if any(keyword in cleaned for keyword in _KEYWORDS[intent]):
                return intent
        return "fallback"

    def _answer(self, intent: str) -> str:
        if intent == "time":
            return self._time_text()
        if intent == "date":
            return self._date_text()
        if intent == "help":
            return HELP_TEXT
        if intent == "identity":
            return IDENTITY_TEXT
        if intent == "thanks":
            return "खुशी हुई! कुछ और पूछना हो तो बताइए।"
        if intent == "greeting":
            return "नमस्ते! मैं श्रद्धा हूँ। पूछिए, क्या जानना है?"
        return FALLBACK_TEXT

    def _time_text(self) -> str:
        moment = self._now()
        return f"अभी समय है {moment.strftime('%H:%M')}।"

    def _date_text(self) -> str:
        moment = self._now()
        weekday = _WEEKDAYS[moment.weekday()]
        month = _MONTHS[moment.month - 1]
        return f"आज {weekday}, {moment.day} {month} {moment.year} है।"
