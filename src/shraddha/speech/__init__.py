"""Speech input and output (Hindi first). Heavy dependencies are imported lazily."""

from __future__ import annotations

from shraddha.speech.tts import (
    Voice,
    available_engines,
    hindi_voices,
    list_windows_voices,
    select_engine,
)

__all__ = [
    "Voice",
    "available_engines",
    "hindi_voices",
    "list_windows_voices",
    "select_engine",
]
