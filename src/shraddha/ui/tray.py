"""System tray presence.

The assistant lives here when the overlay is hidden: left-click toggles the card, the
menu offers the same plus a way out. If the platform has no tray (some Linux sessions,
locked-down Windows kiosks) everything degrades to "the overlay is the app".
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QCursor, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from shraddha.logging_setup import get_logger
from shraddha.ui.icons import app_pixmap

log = get_logger("ui.tray")


class TrayController(QObject):
    """Owns the tray icon and its menu."""

    activated = Signal()
    clear_requested = Signal()
    quit_requested = Signal()

    def __init__(self, hotkey_label: str = "Ctrl+Alt+S", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tray: QSystemTrayIcon | None = None
        self._menu: QMenu | None = None
        self._available = QSystemTrayIcon.isSystemTrayAvailable()

        if not self._available:
            log.warning("no system tray on this platform; the overlay is the only entry point")
            return

        self._tray = QSystemTrayIcon(QIcon(app_pixmap(64)), self)
        self._tray.setToolTip(f"SHRADDHA AI — {hotkey_label} दबाकर खोलिए")

        self._menu = QMenu()
        open_action = QAction("खोलिए / Open", self._menu)
        open_action.triggered.connect(self.activated.emit)

        clear_action = QAction("बातचीत मिटाइए / Clear chat", self._menu)
        clear_action.triggered.connect(self.clear_requested.emit)

        quit_action = QAction("बंद कीजिए / Quit", self._menu)
        quit_action.triggered.connect(self.quit_requested.emit)

        self._menu.addAction(open_action)
        self._menu.addAction(clear_action)
        self._menu.addSeparator()
        self._menu.addAction(quit_action)

        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_activated)

    # ------------------------------------------------------------------ public
    @property
    def is_available(self) -> bool:
        return self._available

    def show(self) -> None:
        if self._tray is not None:
            self._tray.show()

    def hide(self) -> None:
        if self._tray is not None:
            self._tray.hide()

    def set_listening(self, listening: bool) -> None:
        """Swap the tray glyph and tooltip while the microphone is live."""
        if self._tray is None:
            return
        self._tray.setIcon(QIcon(app_pixmap(64, listening=listening)))
        state = "सुन रही हूँ…" if listening else "तैयार"
        self._tray.setToolTip(f"SHRADDHA AI — {state}")

    def notify(self, title: str, message: str) -> None:
        """Balloon/notification, only where the platform supports it."""
        if self._tray is not None and self._tray.supportsMessages():
            self._tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 4000)

    def popup_menu(self) -> None:
        """Show the context menu at the cursor (used by tests and by right-click)."""
        if self._menu is not None:
            self._menu.popup(QCursor.pos())

    # ----------------------------------------------------------------- private
    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.activated.emit()
