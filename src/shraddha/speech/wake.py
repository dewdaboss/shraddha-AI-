"""Wake word matching for "Hey Shraddha" - no model, no extra memory.

Design decision: this module does **no** audio processing. It takes the transcript that
the (already loaded) small recogniser produced for a short utterance and decides whether
the user was addressing the assistant.

Why not openWakeWord? A custom phrase needs a trained model, and a dedicated always-on
neural detector costs RAM and CPU permanently. The lightweight alternative that works
today is to let the VAD decide *when* to listen (free), run the small ASR model only on
those short bursts, and match the result here.

Matching is deliberately forgiving, because recognition is not: "shradha", "shraddha",
"श्रद्धा", "श्रद्घा" and "hey sraddha" are all the assistant's name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Words that may precede the name and carry no meaning of their own.
_LEADING_FILLERS = frozenset(
    {
        "hey",
        "hi",
        "hello",
        "ok",
        "okay",
        "o",
        "oh",
        "arre",
        "are",
        "sun",
        "suno",
        "हे",
        "अरे",
        "ओ",
        "ओए",
        "सुन",
        "सुनो",
        "हाय",
    }
)

#: Known spellings/pronunciations in Latin script.
_LATIN_KEYS = ("shraddha", "shradha", "sraddha", "shardha", "shrddha", "shradhdha")

#: Known spellings in Devanagari.
_DEVANAGARI_KEYS = ("श्रद्धा", "श्रद्घा", "सृद्धा", "श्रद्धा॰")

_PUNCTUATION = "।॥,.!?;:\"'()[]{}<>-/\\|*_"
_ZERO_WIDTH = "\u200c\u200d\u093c"
_MAX_WINDOW = 3


@dataclass(frozen=True, slots=True)
class WakeMatch:
    """Result of looking for the wake phrase in one transcript."""

    matched: bool
    command: str = ""
    phrase: str = ""

    @property
    def has_command(self) -> bool:
        """True when the user said the name *and* a command in one breath."""
        return self.matched and bool(self.command.strip())


def normalise(text: str) -> str:
    """Fold case, punctuation and invisible marks; keep words and scripts."""
    lowered = (text or "").casefold()
    for mark in _ZERO_WIDTH:
        lowered = lowered.replace(mark, "")
    cleaned = "".join(" " if char in _PUNCTUATION else char for char in lowered)
    return " ".join(cleaned.split())


def edit_distance(left: str, right: str, max_distance: int = 3) -> int:
    """Levenshtein distance, bounded: returns ``max_distance + 1`` once it is exceeded."""
    if left == right:
        return 0
    if abs(len(left) - len(right)) > max_distance:
        return max_distance + 1
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            cost = 0 if left_char == right_char else 1
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
        if min(current) > max_distance:
            return max_distance + 1
        previous = current
    return previous[-1]


class WakeWordMatcher:
    """Finds the assistant's name anywhere in a short transcript."""

    def __init__(
        self,
        phrases: tuple[str, ...] | list[str] | None = None,
        fuzzy_distance: int = 2,
    ) -> None:
        self.fuzzy_distance = max(0, fuzzy_distance)
        configured = tuple(phrases) if phrases else ("hey shraddha", "shraddha", "श्रद्धा")
        self.phrases = configured
        #: Spellings are derived from the *configured* phrases only, so a user who
        #: renames the assistant does not keep answering to the old name.
        self._latin_keys: set[str] = set()
        self._devanagari_keys: set[str] = set()
        for phrase in configured:
            for token in normalise(phrase).split():
                if token not in _LEADING_FILLERS:
                    self._add_key(token)

    def _add_key(self, token: str) -> None:
        """Add one configured word, expanding a name into its known spellings."""
        if token in _LATIN_KEYS:
            self._latin_keys.update(_LATIN_KEYS)
        elif token in _DEVANAGARI_KEYS:
            self._devanagari_keys.update(_DEVANAGARI_KEYS)
        elif _is_devanagari(token):
            self._devanagari_keys.add(token)
        else:
            self._latin_keys.add(token)

    # ------------------------------------------------------------------ public
    def matches(self, text: str) -> bool:
        return self.detect(text).matched

    def detect(self, text: str) -> WakeMatch:
        """Look for the name in ``text`` and return the command that follows it."""
        tokens = normalise(text).split()
        if not tokens:
            return WakeMatch(matched=False)

        # Smallest window first: "श्रद्धा, Chrome खोलो" must not swallow "Chrome"
        # into a two-token fuzzy match of the name.
        for size in (1, 2, _MAX_WINDOW):
            for start in range(0, max(0, len(tokens) - size) + 1):
                window = tokens[start : start + size]
                candidate = " ".join(window)
                key = self._match_key(candidate)
                if key is None:
                    continue
                remainder = tokens[:start] + tokens[start + size :]
                command = " ".join(self._strip_fillers(remainder))
                return WakeMatch(matched=True, command=command, phrase=key)
        return WakeMatch(matched=False)

    # ----------------------------------------------------------------- private
    def _match_key(self, candidate: str) -> str | None:
        direct = self._exact(candidate)
        if direct is not None:
            return direct
        if self.fuzzy_distance <= 0:
            return None
        # "hey shraddha" said as "ei shradha": try the words individually too.
        for token in candidate.split():
            if token in _LEADING_FILLERS:
                continue
            found = self._fuzzy(token)
            if found is not None:
                return found
        return None

    def _exact(self, candidate: str) -> str | None:
        if candidate in _LEADING_FILLERS:
            return None
        if candidate in self._latin_keys or candidate in self._devanagari_keys:
            return candidate
        return None

    def _fuzzy(self, token: str) -> str | None:
        if len(token) < 4:
            return None
        keys = self._devanagari_keys if _is_devanagari(token) else self._latin_keys
        for key in keys:
            if edit_distance(token, key, self.fuzzy_distance) <= self.fuzzy_distance:
                return key
        return None

    @staticmethod
    def _strip_fillers(tokens: list[str]) -> list[str]:
        index = 0
        while index < len(tokens) and tokens[index] in _LEADING_FILLERS:
            index += 1
        return tokens[index:]


def _is_devanagari(text: str) -> bool:
    return bool(re.search(r"[\u0900-\u097f]", text))


def contains_stop_phrase(text: str) -> bool:
    """'मेरी बात सुनना बंद करो' and friends - stop listening, regardless of wake state."""
    cleaned = normalise(text)
    return any(
        marker in cleaned
        for marker in (
            "सुनना बंद",
            "सुनना बन्द",
            "बंद करो सुनना",
            "stop listening",
            "sunna band",
            "band karo sunna",
            "mute",
            "म्यूट",
            "चुप हो जाओ",
        )
    )
