"""Catalogs of things the assistant is *allowed* to open.

This is the safety boundary, not a convenience table. Speech recognition output is
untrusted input: it can be wrong in ways that look like a command ("chrome kholo" heard
as "format kholo"). Nothing reaches the operating system unless it resolves to an entry
in these catalogs - never a raw string from the microphone.

Hindi aliases are written the way ASR actually returns them (Devanagari) *and* the way
Hinglish speakers type them (Latin).
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppTarget:
    """An allowlisted application."""

    key: str
    label: str
    aliases: tuple[str, ...]
    executables: tuple[str, ...] = ()
    url: str | None = None

    @property
    def is_web(self) -> bool:
        return self.url is not None


APP_CATALOG: tuple[AppTarget, ...] = (
    AppTarget(
        key="chrome",
        label="Chrome",
        aliases=("chrome", "google chrome", "क्रोम", "गूगल क्रोम", "क्रोम ब्राउज़र"),
        executables=("chrome.exe", "chrome", "google-chrome"),
    ),
    AppTarget(
        key="edge",
        label="Edge",
        aliases=("edge", "microsoft edge", "एज", "एज ब्राउज़र"),
        executables=("msedge.exe", "microsoft-edge", "microsoft-edge-stable"),
    ),
    AppTarget(
        key="notepad",
        label="Notepad",
        aliases=("notepad", "note pad", "नोटपैड", "नोटपेड"),
        executables=("notepad.exe", "notepad", "gedit"),
    ),
    AppTarget(
        key="calculator",
        label="Calculator",
        aliases=("calculator", "calc", "कैलकुलेटर", "कैल्कुलेटर", "हिसाब"),
        executables=("calc.exe", "gnome-calculator", "kcalc"),
    ),
    AppTarget(
        key="explorer",
        label="File Explorer",
        aliases=(
            "explorer",
            "file explorer",
            "files",
            "मेरा कंप्यूटर",
            "फाइल एक्सप्लोरर",
            "फ़ाइल एक्सप्लोरर",
            "फाइल्स",
        ),
        executables=("explorer.exe", "nautilus", "dolphin"),
    ),
    AppTarget(
        key="settings",
        label="Settings",
        aliases=("settings", "सेटिंग्स", "सेटिंग"),
        executables=("SystemSettings.exe", "gnome-control-center"),
    ),
    AppTarget(
        key="vscode",
        label="Visual Studio Code",
        aliases=("vs code", "vscode", "visual studio code", "वीएस कोड"),
        executables=("code.exe", "code"),
    ),
    AppTarget(
        key="paint",
        label="Paint",
        aliases=("paint", "mspaint", "पेंट"),
        executables=("mspaint.exe"),
    ),
    AppTarget(
        key="arena",
        label="Arena AI",
        aliases=("arena", "arena ai", "एरीना", "एरिना", "एरीना एआई"),
        url="https://arena.ai",
    ),
)

#: Only these URLs may ever be opened. An allowlist, not a guess.
WEB_ALLOWLIST: frozenset[str] = frozenset(target.url for target in APP_CATALOG if target.url)

#: Known folders, addressed by keyword. Never by a user-supplied path.
FOLDER_ALIASES: dict[str, tuple[str, ...]] = {
    "downloads": (
        "downloads",
        "download",
        "डाउनलोड",
        "डाउनलोड्स",
        "डाउनलोड फाइल",
        "डाउनलोड फ़ाइल",
        "डाउनलोड फोल्डर",
    ),
    "documents": ("documents", "document", "docs", "डॉक्यूमेंट", "दस्तावेज", "दस्तावेज़", "मेरे दस्तावेज"),
    "desktop": ("desktop", "डेस्कटॉप"),
    "pictures": ("pictures", "photos", "तस्वीरें", "फोटो", "पिक्चर्स"),
    "music": ("music", "संगीत", "गाने", "म्यूजिक"),
    "videos": ("videos", "वीडियो", "वीडियोस"),
    "home": ("home", "home folder", "होम", "यूजर फोल्डर"),
}

#: Windows "known folder" GUIDs (FOLDERID_*), used through the registry.
_WINDOWS_FOLDER_IDS = {
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "documents": "Personal",
    "desktop": "Desktop",
    "pictures": "My Pictures",
    "music": "My Music",
    "videos": "My Video",
}

_UNIX_FOLDER_NAMES = {
    "downloads": "Downloads",
    "documents": "Documents",
    "desktop": "Desktop",
    "pictures": "Pictures",
    "music": "Music",
    "videos": "Videos",
}


def normalise_name(text: str) -> str:
    """Lower-case, strip punctuation and collapse spaces for alias lookup."""
    cleaned = "".join(
        " " if char in "।॥,.!?;:\"'()[]{}<>-_/\\" else char for char in (text or "").casefold()
    )
    # Drop Hindi case-markers that ASR adds inconsistently. Padding with spaces makes
    # the same rule work at the start and the end of the phrase.
    for filler in ("मेरी", "मेरा", "मेरे", "my", "the", "please", "कृपया"):
        cleaned = f" {cleaned} ".replace(f" {filler} ", " ")
    return " ".join(cleaned.split()).strip()


def find_app(name: str) -> AppTarget | None:
    """Resolve a spoken app name to an allowlisted target, or ``None``."""
    candidate = normalise_name(name)
    if not candidate:
        return None

    for target in APP_CATALOG:
        if candidate == target.key or candidate == normalise_name(target.label):
            return target
    for target in APP_CATALOG:
        if any(candidate == normalise_name(alias) for alias in target.aliases):
            return target
    # Last resort: the alias appears inside a longer phrase ("bhai chrome khol do").
    for target in APP_CATALOG:
        if any(normalise_name(alias) in candidate for alias in target.aliases):
            return target
    return None


def find_executable(target: AppTarget) -> str | None:
    """Locate the allowlisted executable on this machine."""
    for name in target.executables:
        found = shutil.which(name)
        if found:
            return found

    if sys.platform != "win32":
        return None

    # Windows keeps browsers outside PATH; check the two standard roots.
    roots = [
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    relative = {
        "chrome": (r"Google\Chrome\Application\chrome.exe",),
        "edge": (r"Microsoft\Edge\Application\msedge.exe",),
        "vscode": (r"Programs\Microsoft VS Code\Code.exe",),
    }.get(target.key, ())
    for root in roots:
        if not root:
            continue
        for suffix in relative:
            candidate = Path(root) / suffix
            if candidate.is_file():
                return str(candidate)
    return None


def find_folder(name: str) -> tuple[str, Path] | None:
    """Resolve a spoken folder name to ``(key, path)`` for an existing folder."""
    candidate = normalise_name(name)
    for key, aliases in FOLDER_ALIASES.items():
        if candidate == key or candidate in aliases:
            path = folder_path(key)
            return (key, path) if path is not None else None
    for key, aliases in FOLDER_ALIASES.items():
        if any(alias in candidate for alias in aliases):
            path = folder_path(key)
            return (key, path) if path is not None else None
    return None


def folder_path(key: str) -> Path | None:
    """Path of a known folder, or ``None`` when it does not exist."""
    if key == "home":
        return Path.home()

    if sys.platform == "win32":
        resolved = _windows_known_folder(key)
        if resolved is not None:
            return resolved

    name = _UNIX_FOLDER_NAMES.get(key)
    if name is None:
        return None
    candidate = Path.home() / name
    return candidate if candidate.is_dir() else None


def _windows_known_folder(key: str) -> Path | None:
    """Read the shell's own folder mapping from the registry (no ctypes gymnastics)."""
    identifier = _WINDOWS_FOLDER_IDS.get(key)
    if identifier is None:
        return None
    try:
        import winreg
    except ImportError:  # pragma: no cover - non-Windows
        return None

    base = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as handle:
            value, _ = winreg.QueryValueEx(handle, identifier)
    except OSError:
        return None
    expanded = Path(os.path.expandvars(str(value)))
    return expanded if expanded.is_dir() else None
