"""Application wiring: tray + overlay + hotkey + single instance + assistant.

The controller below is deliberately constructor-injectable (paths, config) so tests can
build the whole wiring against a temporary home directory without touching the running
assistant or the real event loop.
"""

from __future__ import annotations

import os
import sys

from shraddha import APP_NAME, __version__
from shraddha.assistant import Assistant
from shraddha.config import AppConfig, ConfigError
from shraddha.instance import SingleInstanceLock
from shraddha.logging_setup import get_logger, setup_logging
from shraddha.paths import Paths, get_paths
from shraddha.speech import asr
from shraddha.storage import Database

log = get_logger("ui.app")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_ALREADY_RUNNING = 2
EXIT_NO_QT = 4

WELCOME_TEXT = (
    "नमस्ते! मैं श्रद्धा हूँ।\nहिन्दी या Hinglish में लिखिए — जवाब तुरंत मिलेगा, और सब कुछ आपके कंप्यूटर पर ही रहेगा।"
)
HISTORY_TURNS = 12


class AssistantController:
    """Glue object. One instance per process."""

    def __init__(
        self,
        paths: Paths | None = None,
        config: AppConfig | None = None,
        use_tray: bool = True,
        server_name: str | None = None,
    ) -> None:
        self.paths = paths or get_paths().ensure()
        self.config = config or AppConfig.load(self.paths.config_file)
        self.assistant = Assistant(language=self.config.ui.language)
        self.recognizer = asr.create_recognizer()
        self.db = self._open_database()

        from shraddha.ui.hotkey import GlobalHotkey
        from shraddha.ui.ipc import ActivationServer
        from shraddha.ui.overlay import AssistantOverlay
        from shraddha.ui.tray import TrayController

        self._mic_hint_shown = False
        self.hotkey = GlobalHotkey(self.config.ui.hotkey)
        self.overlay = AssistantOverlay(
            hotkey_label=self.hotkey.label, always_on_top=self.config.ui.always_on_top
        )
        self.tray = TrayController(self.hotkey.label) if use_tray else None
        self.server = ActivationServer(server_name) if server_name else ActivationServer()
        self._lock = SingleInstanceLock(self.paths.lock_file)

        self.overlay.submitted.connect(self.on_submitted)
        self.overlay.mic_toggled.connect(self.on_mic_toggled)
        self.overlay.closed.connect(self._sync_tray_hidden)
        self.server.activated.connect(self.on_activation_requested)
        if self.tray is not None:
            self.tray.activated.connect(self.on_tray_activated)
            self.tray.clear_requested.connect(self.on_clear_chat)
            self.tray.quit_requested.connect(self.on_quit)

        self._restore_history()

    @property
    def has_lock(self) -> bool:
        return self._lock.is_held

    # ------------------------------------------------------------------ setup
    def _open_database(self):
        try:
            return Database(self.paths.db_file)
        except Exception as exc:  # sqlite is optional at runtime
            log.warning("history disabled: %s", exc)
            return None

    def _restore_history(self) -> None:
        self.overlay.append_message(WELCOME_TEXT, "assistant")
        if self.db is None:
            return
        try:
            for turn in self.db.recent_turns(limit=HISTORY_TURNS):
                self.overlay.append_message(turn["text"], turn["role"])
        except Exception as exc:  # a corrupt database must not block startup
            log.warning("could not restore history: %s", exc)

    def start(self, show_overlay: bool = True) -> bool:
        """Take ownership of the session. False when another instance is running."""
        if not self._lock.acquire():
            return False
        self.server.start()
        if not self.hotkey.register():
            log.warning("global hotkey unavailable; use the tray or the overlay")
        if self.tray is not None:
            self.tray.show()
        if show_overlay:
            self.overlay.show_overlay()
        log.info("%s AI %s ready", APP_NAME, __version__)
        return True

    def shutdown(self) -> None:
        self.hotkey.unregister()
        self.server.stop()
        if self.tray is not None:
            self.tray.hide()
        self.overlay.hide()
        self.recognizer.close()
        self._lock.release()
        log.info("shutdown complete")

    # ------------------------------------------------------------------ slots
    def on_submitted(self, text: str) -> None:
        """A message arrived from the input field."""
        self.overlay.append_message(text, "user")
        self._persist("user", text)

        reply = self.assistant.respond(text)
        self.overlay.append_message(reply.text, reply.kind)
        self._persist(reply.kind, reply.text)
        log.debug("intent=%s chars=%s", reply.intent, len(reply.text))

    def on_mic_toggled(self, listening: bool) -> None:
        """Microphone button pressed. Phase 2 replaces the placeholder recogniser."""
        if listening and not self.recognizer.is_available:
            self.overlay.set_listening(False)
            if not self._mic_hint_shown:
                self._mic_hint_shown = True
                self.overlay.append_message(self.recognizer.unavailable_reason, "system")
                log.info("microphone pressed but no recogniser is installed yet")
            return

        started = self.recognizer.start() if listening else bool(self.recognizer.stop())
        self.overlay.set_listening(listening and started)
        if self.tray is not None:
            self.tray.set_listening(listening and started)

    def on_tray_activated(self) -> None:
        self.overlay.toggle()

    def on_activation_requested(self) -> None:
        """A second launch asked us to come forward."""
        self.overlay.show_overlay()

    def on_clear_chat(self) -> None:
        self.overlay.clear_chat()
        if self.db is not None:
            try:
                self.db.clear_conversation()
            except Exception as exc:
                log.warning("could not clear history: %s", exc)

    def on_quit(self) -> None:
        from PySide6.QtWidgets import QApplication

        self.shutdown()
        application = QApplication.instance()
        if application is not None:
            application.quit()

    # --------------------------------------------------------------- internals
    def _sync_tray_hidden(self) -> None:
        if self.tray is not None:
            self.tray.set_listening(False)

    def _persist(self, role: str, text: str) -> None:
        if self.db is None:
            return
        try:
            self.db.add_turn(role, text)
        except Exception as exc:
            log.warning("could not store turn: %s", exc)


def _configure_windows_shell(app) -> None:
    """Group the app under its own taskbar identity on Windows (cosmetic, guarded)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore[attr-defined]
            "dewdaboss.shraddha.ai.1"
        )
    except (AttributeError, OSError) as exc:
        log.debug("could not set AppUserModelID: %s", exc)


def run_ui(
    paths: Paths | None = None,
    config: AppConfig | None = None,
    smoke_seconds: float | None = None,
) -> int:
    """Start the desktop interface. Returns a process exit code."""
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        print(
            "The desktop interface needs PySide6.\n"
            "  pip install -e '.[ui]'\n"
            f"(import error: {exc})",
            file=sys.stderr,
        )
        return EXIT_NO_QT

    from shraddha.ui.icons import app_icon
    from shraddha.ui.ipc import notify_running_instance

    resolved_paths = (paths or get_paths()).ensure()
    setup_logging(level="DEBUG" if _verbose() else "INFO", log_file=resolved_paths.log_file)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(f"{APP_NAME} AI")
    app.setApplicationDisplayName(f"{APP_NAME} AI")
    app.setOrganizationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(app_icon(256))
    app.setQuitOnLastWindowClosed(False)
    _configure_windows_shell(app)

    try:
        loaded = config or AppConfig.load(resolved_paths.config_file)
    except ConfigError as exc:
        log.error("configuration is invalid, using defaults: %s", exc)
        loaded = AppConfig()

    controller = AssistantController(paths=resolved_paths, config=loaded)
    if not controller.start(show_overlay=not loaded.ui.start_minimised):
        log.info("another instance is already running; asking it to show itself")
        if notify_running_instance():
            return EXIT_ALREADY_RUNNING
        log.warning("the running instance did not answer; continuing is not possible")
        return EXIT_ALREADY_RUNNING

    if smoke_seconds is not None:
        # Internal measurement hook: prove the UI is up, then exit cleanly.
        print("SHRADDHA_UI_READY", flush=True)
        QTimer.singleShot(int(smoke_seconds * 1000), controller.on_quit)

    try:
        return app.exec()
    finally:
        if controller.has_lock:  # on_quit may already have released it
            controller.shutdown()


def _verbose() -> bool:
    return os.environ.get("SHRADDHA_DEBUG", "") not in ("", "0")


def main() -> int:
    """``python -m shraddha.ui``"""
    return run_ui()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
