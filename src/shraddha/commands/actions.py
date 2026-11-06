"""The only module that touches the operating system on behalf of a voice command.

Threat model: the text came from a microphone and may be wrong, malformed or adversarial.
Therefore:

* every target is re-resolved from the allowlists, ignoring anything in ``args`` that
  could have been altered;
* ``subprocess`` is always called with an argv list and ``shell=False`` - no shell, no
  string interpolation, no ``&``/``|`` surprises;
* an unknown intent is a *no-op*, never a fallback to "just run it".
"""

from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from shraddha.commands.apps import (
    FOLDER_ALIASES,
    WEB_ALLOWLIST,
    find_app,
    find_executable,
    folder_path,
)
from shraddha.commands.router import (
    INTENT_APP_OPEN,
    INTENT_CLIPBOARD_COPY,
    INTENT_CLIPBOARD_READ,
    INTENT_FILE_SEARCH,
    INTENT_FOLDER_OPEN,
    INTENT_NOTE_ADD,
    INTENT_NOTE_CLEAR,
    INTENT_NOTE_READ,
    INTENT_POWER,
    INTENT_TIMER_CANCEL,
    INTENT_TIMER_SET,
    INTENT_TIMER_STATUS,
    INTENT_VOLUME,
    INTENT_WEB_OPEN,
    INTENT_WINDOW,
    Command,
)
from shraddha.logging_setup import get_logger

log = get_logger("commands")

NOT_FOUND = "यह ऐप इस कंप्यूटर पर नहीं मिला।"
REFUSED = "सुरक्षा कारणों से यह कार्य नहीं किया जा सकता।"

#: Phase 4 skills that need Windows APIs. Said honestly instead of failing silently.
WINDOWS_ONLY = "यह सुविधा इस सिस्टम पर उपलब्ध नहीं है - यह Windows पर काम करती है।"
NO_TIMER = "टाइमर सेवा उपलब्ध नहीं है।"
NO_NOTES = "नोट्स के लिए डेटाबेस उपलब्ध नहीं है।"
VOLUME_SET_UNSUPPORTED = (
    "अभी मैं वॉल्यूम सीधे सेट नहीं कर सकती - 'volume बढ़ाओ' या 'volume कम करो' कहिए।"
)

#: Directories that are never worth walking when the user says "ढूँढो".
SKIP_DIRS = frozenset(
    {
        "node_modules",
        ".git",
        "__pycache__",
        "appdata",
        "windows",
        "$recycle.bin",
        "system volume information",
        ".venv",
        "venv",
        "site-packages",
    }
)
MAX_SEARCH_DEPTH = 4

#: Windows moves the volume by 2 % per media-key press; five presses ≈ 10 %.
VOLUME_KEY_STEPS = 5


@dataclass(frozen=True, slots=True)
class ActionResult:
    """What happened, in words the assistant can speak."""

    ok: bool
    message: str
    intent: str = ""
    detail: str = ""


@dataclass
class ActionExecutor:
    """Executes validated commands, or records them in dry-run mode."""

    dry_run: bool = False
    popen: Callable[..., object] = subprocess.Popen
    url_opener: Callable[[str], bool] = webbrowser.open
    path_opener: Callable[[str], None] | None = None
    allow_power_actions: bool = False
    history: list[Command] = field(default_factory=list)

    # --- Phase 4 skills. Every OS dependency is injectable, so the decisions are
    # testable on any platform and nothing runs during a test.
    timer: object | None = None  # AlarmTimer-like: start/cancel/status
    notes_add: Callable[[str], int] | None = None
    notes_recent: Callable[[int], list[str]] | None = None
    notes_clear: Callable[[], int] | None = None
    clipboard_read: Callable[[], str] | None = None
    clipboard_write: Callable[[str], bool] | None = None
    volume_control: Callable[[str], bool] | None = None  # "up" | "down" | "mute"
    window_control: Callable[[str], bool] | None = None  # "minimize" | "close"
    search_roots: Callable[[], tuple[Path, ...]] | None = None
    search_limit: int = 12

    def execute(self, command: Command) -> ActionResult:
        self.history.append(command)
        handlers = {
            INTENT_APP_OPEN: self._open_app,
            INTENT_WEB_OPEN: self._open_web,
            INTENT_FOLDER_OPEN: self._open_folder,
            INTENT_POWER: self._power,
            INTENT_TIMER_SET: self._timer,
            INTENT_TIMER_CANCEL: self._timer,
            INTENT_TIMER_STATUS: self._timer,
            INTENT_NOTE_ADD: self._note,
            INTENT_NOTE_READ: self._note,
            INTENT_NOTE_CLEAR: self._note,
            INTENT_CLIPBOARD_COPY: self._clipboard,
            INTENT_CLIPBOARD_READ: self._clipboard,
            INTENT_VOLUME: self._volume,
            INTENT_WINDOW: self._window,
            INTENT_FILE_SEARCH: self._file_search,
        }
        handler = handlers.get(command.intent)
        if handler is None:
            return ActionResult(True, command.spoken, command.intent, "no-op: not an OS action")
        if self.dry_run:
            return ActionResult(
                True,
                f"[dry-run] {command.intent} {command.args}",
                command.intent,
                "dry_run",
            )
        return handler(command)

    # ------------------------------------------------------------------- apps
    def _open_app(self, command: Command) -> ActionResult:
        target = find_app(command.target)
        if target is None:
            log.warning("refused app.open for unknown target %r", command.target)
            return ActionResult(False, REFUSED, command.intent, "unknown_target")
        if target.is_web:
            # The URL comes from the catalog, never from the transcript.
            return self._open_url(target.url or "", command)

        executable = find_executable(target)
        if not executable:
            return ActionResult(False, f"{target.label}: {NOT_FOUND}", command.intent, "not_found")
        try:
            self.popen([executable], shell=False, close_fds=True)
        except OSError as exc:
            log.warning("could not launch %s: %s", executable, exc)
            return ActionResult(False, f"{target.label} खोल नहीं सकी।", command.intent, str(exc))
        return ActionResult(True, command.spoken, command.intent, executable)

    # -------------------------------------------------------------------- web
    def _open_web(self, command: Command) -> ActionResult:
        return self._open_url(command.args.get("url", ""), command)

    def _open_url(self, url: str, command: Command) -> ActionResult:
        if url not in WEB_ALLOWLIST:
            log.warning("refused web.open for non-allowlisted url %r", url)
            return ActionResult(False, REFUSED, command.intent, "url_not_allowed")
        try:
            self.url_opener(url)
        except Exception as exc:  # webbrowser can raise on headless systems
            log.warning("could not open %s: %s", url, exc)
            return ActionResult(False, "वेबसाइट नहीं खुल सकी।", command.intent, str(exc))
        return ActionResult(True, command.spoken, command.intent, url)

    # ----------------------------------------------------------------- folder
    def _open_folder(self, command: Command) -> ActionResult:
        key = command.target
        if key not in FOLDER_ALIASES:
            log.warning("refused folder.open for unknown key %r", key)
            return ActionResult(False, REFUSED, command.intent, "unknown_folder")

        path = folder_path(key)  # re-resolved: never the path in args
        if path is None or not path.is_dir():
            return ActionResult(False, "यह फोल्डर नहीं मिला।", command.intent, "not_found")
        try:
            self._open_path(path)
        except OSError as exc:
            log.warning("could not open %s: %s", path, exc)
            return ActionResult(False, "फोल्डर नहीं खुल सका।", command.intent, str(exc))
        return ActionResult(True, command.spoken, command.intent, str(path))

    def _open_path(self, path: Path) -> None:
        if self.path_opener is not None:
            self.path_opener(str(path))
            return
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
            return
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        self.popen([opener, str(path)], shell=False, close_fds=True)

    # ------------------------------------------------------------------- timer
    def _timer(self, command: Command) -> ActionResult:
        if self.timer is None:
            return ActionResult(False, NO_TIMER, command.intent, "no_timer")
        if command.intent == INTENT_TIMER_CANCEL:
            return ActionResult(True, _call(self.timer, "cancel"), command.intent, "timer.cancel")
        if command.intent == INTENT_TIMER_STATUS:
            return ActionResult(True, _call(self.timer, "status"), command.intent, "timer.status")
        try:
            seconds = int(command.args.get("seconds", "0"))
        except (TypeError, ValueError):
            seconds = 0
        if seconds <= 0:
            return ActionResult(False, "टाइमर की अवधि समझ नहीं आई।", command.intent, "bad_duration")
        return ActionResult(
            True, _call(self.timer, "start", seconds), command.intent, f"timer.set:{seconds}"
        )

    # ------------------------------------------------------------------- notes
    def _note(self, command: Command) -> ActionResult:
        if command.intent == INTENT_NOTE_ADD:
            if self.notes_add is None:
                return ActionResult(False, NO_NOTES, command.intent, "no_store")
            text = (command.args.get("text") or "").strip()
            if not text:
                return ActionResult(False, "क्या नोट लिखना है?", command.intent, "empty_note")
            try:
                self.notes_add(text)
            except Exception as exc:  # a corrupt database must not crash the chat
                log.warning("could not save note: %s", exc)
                return ActionResult(False, "नोट सेव नहीं हो सका।", command.intent, str(exc))
            return ActionResult(True, command.spoken or "नोट लिख लिया।", command.intent, "stored")

        if command.intent == INTENT_NOTE_READ:
            if self.notes_recent is None:
                return ActionResult(False, NO_NOTES, command.intent, "no_store")
            try:
                notes = list(self.notes_recent(5))
            except Exception as exc:
                log.warning("could not read notes: %s", exc)
                return ActionResult(False, "नोट्स पढ़े नहीं जा सके।", command.intent, str(exc))
            if not notes:
                return ActionResult(True, "अभी कोई नोट नहीं है।", command.intent, "empty")
            lines = [f"{index}. {text}" for index, text in enumerate(notes, start=1)]
            spoken = "आपके नोट्स:\n" + "\n".join(lines)
            return ActionResult(True, spoken, command.intent, f"{len(notes)} notes")

        # INTENT_NOTE_CLEAR
        if self.notes_clear is None:
            return ActionResult(False, NO_NOTES, command.intent, "no_store")
        try:
            removed = int(self.notes_clear())
        except Exception as exc:
            log.warning("could not clear notes: %s", exc)
            return ActionResult(False, "नोट्स साफ़ नहीं हो सके।", command.intent, str(exc))
        if not removed:
            return ActionResult(True, "साफ़ करने के लिए कोई नोट नहीं था।", command.intent, "empty")
        return ActionResult(True, f"{removed} नोट हटा दिए।", command.intent, f"{removed} removed")

    # --------------------------------------------------------------- clipboard
    def _clipboard(self, command: Command) -> ActionResult:
        if command.intent == INTENT_CLIPBOARD_COPY:
            text = (command.args.get("text") or "").strip()
            if not text:
                return ActionResult(False, "क्या कॉपी करना है?", command.intent, "empty_text")
            writer = self.clipboard_write
            if writer is None:
                return ActionResult(False, WINDOWS_ONLY, command.intent, "unsupported")
            try:
                ok = bool(writer(text))
            except Exception as exc:
                log.warning("clipboard write failed: %s", exc)
                return ActionResult(False, "क्लिपबोर्ड पर कॉपी नहीं हो सका।", command.intent, str(exc))
            if not ok:
                return ActionResult(False, "क्लिपबोर्ड पर कॉपी नहीं हो सका।", command.intent, "failed")
            return ActionResult(True, command.spoken, command.intent, f"{len(text)} chars")

        reader = self.clipboard_read
        if reader is None:
            return ActionResult(False, WINDOWS_ONLY, command.intent, "unsupported")
        try:
            text = str(reader() or "").strip()
        except Exception as exc:
            log.warning("clipboard read failed: %s", exc)
            return ActionResult(False, "क्लिपबोर्ड पढ़ा नहीं जा सका।", command.intent, str(exc))
        if not text:
            return ActionResult(True, "क्लिपबोर्ड खाली है।", command.intent, "empty")
        if len(text) > 500:
            text = f"{text[:500]}…"
        return ActionResult(True, f"क्लिपबोर्ड में है:\n{text}", command.intent, "read")

    # ------------------------------------------------------------------ volume
    def _volume(self, command: Command) -> ActionResult:
        action = (command.args.get("action") or "").lower()
        if action == "set":
            # Deliberate: absolute volume needs Core Audio COM. Relative steps work with
            # documented Win32 virtual keys, so say what *is* possible instead of guessing.
            return ActionResult(
                False, VOLUME_SET_UNSUPPORTED, command.intent, "absolute_unsupported"
            )
        control = self.volume_control
        if control is None:
            return ActionResult(False, WINDOWS_ONLY, command.intent, "unsupported")
        try:
            ok = bool(control(action))
        except Exception as exc:
            log.warning("volume control failed: %s", exc)
            return ActionResult(False, "आवाज़ बदल नहीं सकी।", command.intent, str(exc))
        if not ok:
            return ActionResult(False, "आवाज़ बदल नहीं सकी।", command.intent, "failed")
        return ActionResult(True, command.spoken or "आवाज़ बदल दी।", command.intent, action)

    # ------------------------------------------------------------------ window
    def _window(self, command: Command) -> ActionResult:
        action = (command.args.get("action") or "").lower()
        control = self.window_control
        if control is None:
            return ActionResult(False, WINDOWS_ONLY, command.intent, "unsupported")
        try:
            ok = bool(control(action))
        except Exception as exc:
            log.warning("window control failed: %s", exc)
            return ActionResult(False, "विंडो पर काम नहीं हो सका।", command.intent, str(exc))
        if not ok:
            return ActionResult(False, "कोई सक्रिय विंडो नहीं मिली।", command.intent, "no_window")
        spoken = (
            "विंडो बंद करने का अनुरोध भेज दिया।"
            if action == "close"
            else "विंडो छोटा कर दिया।"
        )
        return ActionResult(True, spoken, command.intent, action)

    # ------------------------------------------------------------- file search
    def _file_search(self, command: Command) -> ActionResult:
        query = (command.args.get("query") or "").strip()
        if not query:
            return ActionResult(False, "क्या ढूँढना है?", command.intent, "empty_query")
        roots = self._search_roots_for(command.args.get("folder") or "")
        if not roots:
            return ActionResult(False, "खोजने के लिए कोई फोल्डर नहीं मिला।", command.intent, "no_roots")
        matches = search_files(roots, query, limit=self.search_limit)
        if not matches:
            return ActionResult(
                False, f"'{query}' नाम की कोई फाइल नहीं मिली।", command.intent, "no_match"
            )
        names = ", ".join(path.name for path in matches[:6])
        extra = "" if len(matches) <= 6 else f" (और {len(matches) - 6})"
        return ActionResult(
            True,
            f"{len(matches)} फाइल मिली: {names}{extra}",
            command.intent,
            "; ".join(str(path) for path in matches),
        )

    def _search_roots_for(self, folder: str) -> list[Path]:
        if folder:
            path = folder_path(folder)
            candidates = [path] if path is not None else []
        elif self.search_roots is not None:
            try:
                candidates = list(self.search_roots())
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("could not list search roots: %s", exc)
                candidates = []
        else:
            candidates = [folder_path(key) for key in ("documents", "desktop", "downloads")]
        return [Path(path) for path in candidates if path is not None and Path(path).is_dir()]

    # ------------------------------------------------------------------- power
    def _power(self, command: Command) -> ActionResult:
        # Deliberately not implemented: an assistant that can be talked into shutting a
        # machine down is a liability while recognition is still imperfect.
        message = (
            f"कंप्यूटर {command.args.get('action', 'शटडाउन')} करना अभी समर्थित नहीं है।"
            if self.allow_power_actions
            else command.spoken or REFUSED
        )
        log.info("power action blocked: %s", command.args.get("action"))
        return ActionResult(False, message, command.intent, "power_disabled")


def windows_skills() -> dict[str, object]:
    """The real Windows implementations of the Phase 4 skills.

    Empty on every other platform, so the executor answers honestly instead of pretending.
    Kept in this module because it is *the* module allowed to call the OS.
    """
    if sys.platform != "win32":
        return {}
    return {
        "clipboard_read": _win_clipboard_read,
        "clipboard_write": _win_clipboard_write,
        "volume_control": _win_volume,
        "window_control": _win_window,
    }


def _win_clipboard_read() -> str:
    import win32clipboard

    win32clipboard.OpenClipboard()
    try:
        data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        return str(data or "")
    finally:
        win32clipboard.CloseClipboard()


def _win_clipboard_write(text: str) -> bool:
    import win32clipboard

    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()
    return True


def _win_volume(action: str, steps: int = VOLUME_KEY_STEPS) -> bool:
    """Relative volume via the documented media keys (no COM, no polling)."""
    import ctypes

    keys = {"up": 0xAF, "down": 0xAE, "mute": 0xAD}
    key = keys.get(action)
    if key is None:
        return False
    presses = 1 if action == "mute" else max(1, steps)
    for _ in range(presses):
        ctypes.windll.user32.keybd_event(key, 0, 0, 0)  # type: ignore[attr-defined]
        ctypes.windll.user32.keybd_event(key, 0, 2, 0)  # KEYEVENTF_KEYUP
    return True


def _win_window(action: str) -> bool:
    """Minimise or politely close the foreground window."""
    import ctypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    if action == "minimize":
        return bool(user32.ShowWindow(hwnd, 6))  # SW_MINIMIZE
    if action == "close":
        return bool(user32.PostMessageW(hwnd, 0x0010, 0, 0))  # WM_CLOSE
    return False


def startswith_tokens(name: str, tokens: list[str]) -> bool:
    """True when every query token appears in ``name`` (case-insensitive, order-free)."""
    folded = name.casefold()
    return all(token in folded for token in tokens)


def search_files(
    roots: list[Path] | tuple[Path, ...],
    query: str,
    *,
    limit: int = 12,
    max_depth: int = MAX_SEARCH_DEPTH,
) -> list[Path]:
    """Find files whose name contains every word of ``query``. Read-only, bounded.

    Deliberately not ``rglob("*")``: the walk stops at ``max_depth``, skips noise
    directories, and stops as soon as ``limit`` matches are found so a huge folder
    cannot hang the GUI thread.
    """
    tokens = [token for token in query.casefold().split() if token]
    if not tokens:
        return []
    found: list[Path] = []
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        base_depth = len(root.parts)
        for path in sorted(root.rglob("*"), key=lambda item: str(item).casefold()):
            if len(path.parts) - base_depth > max_depth:
                continue
            if any(part.casefold() in SKIP_DIRS for part in path.parts):
                continue
            if not path.is_file():
                continue
            if startswith_tokens(path.name, tokens):
                found.append(path)
                if len(found) >= limit:
                    return found
    return found


def _call(target: object, method: str, *args: object) -> str:
    """Call an injected skill object, turning a broken one into an honest sentence."""
    function = getattr(target, method, None)
    if not callable(function):
        return NO_TIMER
    try:
        return str(function(*args))
    except Exception as exc:  # pragma: no cover - injected object misbehaving
        log.warning("skill %s failed: %s", method, exc)
        return "यह काम पूरा नहीं हो सका।"


def describe_history(history: list[Command]) -> list[str]:
    """Compact trace used by tests and debug logs."""
    return [f"{command.intent}:{command.args.get('target', '')}" for command in history]
