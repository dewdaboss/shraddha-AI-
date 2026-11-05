"""Global hotkey registration.

Uses Win32 ``RegisterHotKey`` - **not** a low-level keyboard hook. That choice matters:
hooks see every keystroke (a privacy and antivirus problem) and cost CPU on each event,
while ``RegisterHotKey`` is a free, OS-level registration that only wakes us when the
exact combination is pressed.

The message arrives through Qt's native event filter, so no extra thread or message
pump is needed. On platforms without the API, :meth:`GlobalHotkey.register` simply
returns ``False`` and the tray/overlay remain the entry points.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

from shraddha.hotkey import HotkeyError, HotkeySpec, parse_hotkey
from shraddha.logging_setup import get_logger

log = get_logger("ui.hotkey")

WM_HOTKEY = 0x0312
_NATIVE_EVENT_TYPES = (b"windows_generic_MSG", b"windows_dispatcher_MSG")


class _HotkeyEventFilter(QAbstractNativeEventFilter):
    """Translates ``WM_HOTKEY`` into a Qt signal."""

    def __init__(self, hotkey_id: int, callback) -> None:
        super().__init__()
        self._id = hotkey_id
        self._callback = callback

    def nativeEventFilter(self, event_type, message):
        if event_type not in _NATIVE_EVENT_TYPES:
            return False, 0
        try:
            msg = wintypes.MSG.from_address(int(message))
        except (TypeError, ValueError):
            return False, 0
        if msg.message == WM_HOTKEY and int(msg.wParam) == self._id:
            self._callback()
            return True, 0
        return False, 0


class GlobalHotkey(QObject):
    """Registers the configured combination system-wide."""

    triggered = Signal()

    _NEXT_ID = 0xB00B  # arbitrary but stable, inside the app-private range

    def __init__(self, text: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._raw = text
        self._spec: HotkeySpec | None = None
        self._registered = False
        self._filter: _HotkeyEventFilter | None = None
        self._hotkey_id = GlobalHotkey._NEXT_ID
        GlobalHotkey._NEXT_ID += 1

    @property
    def is_registered(self) -> bool:
        return self._registered

    @property
    def spec(self) -> HotkeySpec | None:
        return self._spec

    @property
    def label(self) -> str:
        """Canonical display text, even before (or without) registration.

        An unparsable configuration falls back to the raw string so the user can see
        exactly what they typed while fixing it.
        """
        if self._spec is not None:
            return self._spec.text
        try:
            return parse_hotkey(self._raw).text
        except HotkeyError:
            return self._raw

    def register(self) -> bool:
        """Parse and register. Returns ``False`` (never raises) when unavailable."""
        try:
            self._spec = parse_hotkey(self._raw)
        except HotkeyError as exc:
            log.error("invalid hotkey %r: %s", self._raw, exc)
            return False

        if sys.platform != "win32":
            log.info("global hotkey needs Windows; using the tray and overlay instead")
            return False

        try:
            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            if not user32.RegisterHotKey(
                None, self._hotkey_id, self._spec.register_modifiers, self._spec.virtual_key
            ):
                log.warning("hotkey %s is already taken by another application", self._spec.text)
                return False
        except (AttributeError, OSError) as exc:
            log.warning("could not register the global hotkey: %s", exc)
            return False

        self._filter = _HotkeyEventFilter(self._hotkey_id, self.triggered.emit)
        application = _application()
        if application is None:
            log.warning("no QApplication yet; cannot install the hotkey event filter")
            self._unregister_os()
            return False
        application.installNativeEventFilter(self._filter)
        self._registered = True
        log.info("global hotkey registered: %s", self._spec.text)
        return True

    def unregister(self) -> None:
        if not self._registered and self._filter is None:
            return
        application = _application()
        if self._filter is not None and application is not None:
            application.removeNativeEventFilter(self._filter)
        self._filter = None
        self._unregister_os()
        self._registered = False

    def _unregister_os(self) -> None:
        if sys.platform != "win32" or self._spec is None:
            return
        try:
            ctypes.windll.user32.UnregisterHotKey(None, self._hotkey_id)  # type: ignore[attr-defined]
        except (AttributeError, OSError) as exc:
            log.debug("UnregisterHotKey failed: %s", exc)


def _application():
    """Return the running QApplication, if any (import kept local for speed)."""
    from PySide6.QtWidgets import QApplication

    return QApplication.instance()
