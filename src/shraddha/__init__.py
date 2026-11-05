"""SHRADDHA AI - a lightweight, local-first, Hindi-first Windows voice assistant.

The core package deliberately depends on the standard library only. Optional
capabilities (Qt UI, audio capture, ASR, TTS) live in extras and must be imported
lazily so that an unused feature costs no memory.
"""

from __future__ import annotations

__all__ = ["APP_NAME", "ORGANISATION", "__version__"]

__version__ = "0.1.0"

#: Human-facing application name ("" used in the tray, window titles and logs).
APP_NAME = "Shraddha"

#: Folder name used under %LOCALAPPDATA%.
ORGANISATION = "Shraddha"
