"""Application wiring: tray + overlay + hotkey + voice pipeline + commands.

The controller is constructor-injectable (paths, config, executor) so the entire wiring
can be tested against a temporary home directory with a fake microphone, a fake
recogniser and a dry-run executor - no audio device, no model, and nothing launched.
"""

from __future__ import annotations

import contextlib
import os
import sys

from shraddha import APP_NAME, __version__
from shraddha.ai import STATUS_CONSENT, AiService, consent_intent, make_service
from shraddha.assistant import KIND_SYSTEM, Assistant
from shraddha.commands import (
    INTENT_INFO_DATE,
    INTENT_INFO_TIME,
    INTENT_UNKNOWN,
    INTENT_VOICE_STOP,
    INTENT_VOICE_SWITCH,
    ActionExecutor,
    CommandRouter,
    ConfirmationGate,
    ConfirmationOutcome,
)
from shraddha.config import AppConfig, ConfigError
from shraddha.instance import SingleInstanceLock
from shraddha.logging_setup import get_logger, setup_logging
from shraddha.paths import Paths, get_paths
from shraddha.speech import tts as tts_module
from shraddha.speech.service import VoiceService, VoiceState
from shraddha.storage import Database

log = get_logger("ui.app")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_ALREADY_RUNNING = 2
EXIT_NO_QT = 4

#: AI error codes that are really "the feature is off", not "your question failed".
_AI_STATUS_CODES = ("off", "no_key", "consent_required", "no_provider", "no_sdk", "sdk_missing")

WELCOME_TEXT = (
    "नमस्ते! मैं श्रद्धा हूँ।\nहिन्दी या Hinglish में लिखिए — जवाब तुरंत मिलेगा, और सब कुछ आपके कंप्यूटर पर ही रहेगा।"
)
HISTORY_TURNS = 12

STATUS_READY = "तैयार - आवाज़ के लिए माइक दबाइए"
STATUS_LISTENING = "सुन रही हूँ… बोलिए"
STATUS_WAKE = "श्रद्धा कहकर बुलाइए"
STATUS_THINKING = "सोच रही हूँ…"
STATUS_MUTED = "माइक्रोफ़ोन म्यूट है"
STATUS_AI_THINKING = "क्लाउड AI से जवाब आ रहा है…"


class AssistantController:
    """Glue object. One instance per process."""

    def __init__(
        self,
        paths: Paths | None = None,
        config: AppConfig | None = None,
        use_tray: bool = True,
        server_name: str | None = None,
        capture_factory=None,
        recognizer_factory=None,
        executor: ActionExecutor | None = None,
        tts_engine=None,
        ai_service: AiService | None = None,
    ) -> None:
        self.paths = paths or get_paths().ensure()
        self.config = config or AppConfig.load(self.paths.config_file)
        self.assistant = Assistant(language=self.config.ui.language)
        self.db = self._open_database()

        from shraddha.ui.ai import AiBridge
        from shraddha.ui.hotkey import GlobalHotkey
        from shraddha.ui.ipc import ActivationServer
        from shraddha.ui.overlay import AssistantOverlay
        from shraddha.ui.tray import TrayController
        from shraddha.ui.voice import VoiceBridge

        self.hotkey = GlobalHotkey(self.config.ui.hotkey)
        self.overlay = AssistantOverlay(
            hotkey_label=self.hotkey.label, always_on_top=self.config.ui.always_on_top
        )
        self.tray = TrayController(self.hotkey.label) if use_tray else None
        self.server = ActivationServer(server_name) if server_name else ActivationServer()
        self._lock = SingleInstanceLock(self.paths.lock_file)

        # --- voice pipeline (Phase 2) -------------------------------------
        self.voice = VoiceService(
            config=self.config,
            models_dir=self.paths.models,
            capture_factory=capture_factory,
            recognizer_factory=recognizer_factory,
        )
        self.bridge = VoiceBridge(self.voice)
        self.router = CommandRouter(
            allow_power_actions=self.config.commands.allow_power_actions,
            enabled=self.config.commands.enabled,
        )
        self.executor = executor or ActionExecutor(
            allow_power_actions=self.config.commands.allow_power_actions
        )
        self.confirmation = ConfirmationGate()
        # --- cloud intelligence (Phase 3, opt-in) -------------------------
        # Constructing the service opens no socket: the provider is built lazily and only
        # when the three-way gate (enabled + provider + key + consent) is open.
        self.ai: AiService = ai_service or make_service(self.config.llm)
        self.ai_bridge = AiBridge(self.ai)
        self._ai_notice_shown = False
        self._ai_source = "typed"
        self.tts = tts_engine or tts_module.create_engine(
            engine=self.config.tts.engine,
            voice=self.config.tts.voice,
            rate=self.config.tts.rate,
            volume=self.config.tts.volume,
            configured_piper=self.config.tts.piper_model,
            models_dir=self.paths.models,
        )

        # --- signals -------------------------------------------------------
        self.overlay.submitted.connect(self.on_submitted)
        self.overlay.mic_toggled.connect(self.on_mic_toggled)
        self.overlay.mute_toggled.connect(self.on_mute_toggled)
        self.overlay.closed.connect(self._sync_tray_hidden)
        self.overlay.closed.connect(self._cancel_ai)
        self.server.activated.connect(self.on_activation_requested)
        self.bridge.final.connect(self.on_voice_final)
        self.bridge.partial.connect(self.overlay.set_partial)
        self.bridge.state_changed.connect(self.on_voice_state)
        self.bridge.error.connect(self.on_voice_error)
        self.bridge.wake.connect(self.on_wake)
        self.bridge.muted.connect(self.on_mic_muted)
        self.ai_bridge.partial.connect(self.on_ai_partial)
        self.ai_bridge.final.connect(self.on_ai_final)
        self.ai_bridge.error.connect(self.on_ai_error)
        self.ai_bridge.cancelled.connect(self.on_ai_cancelled)
        if self.tray is not None:
            self.tray.activated.connect(self.on_tray_activated)
            self.tray.clear_requested.connect(self.on_clear_chat)
            self.tray.quit_requested.connect(self.on_quit)

        self._shut_down = False
        self._restore_history()
        self._announce_capabilities()

    # ------------------------------------------------------------------ setup
    @property
    def has_lock(self) -> bool:
        return self._lock.is_held

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

    def _announce_capabilities(self) -> None:
        """Tell the user honestly what voice input can do on *this* machine."""
        mic_ok, mic_reason = self.voice.mic_status()
        if not mic_ok:
            self.overlay.append_message(f"आवाज़ से सुनना उपलब्ध नहीं: {mic_reason}", KIND_SYSTEM)
            self.overlay.set_voice_status("माइक उपलब्ध नहीं - टाइप कीजिए", "error")
            return
        if self.config.wake.mode == "push_to_talk":
            self.overlay.set_voice_status(STATUS_READY, "idle")

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
        if self.config.wake.mode == "phrase":
            self.overlay.set_voice_status(STATUS_WAKE, "listening")
            self.bridge.start(mode="phrase")
        log.info("%s AI %s ready", APP_NAME, __version__)
        return True

    def shutdown(self) -> None:
        """Idempotent: the tray, the window manager and tests may all ask for it."""
        if self._shut_down:
            return
        self._shut_down = True
        self.hotkey.unregister()
        self.server.stop()
        self.ai_bridge.shutdown()
        self.bridge.shutdown()
        self._detach_bridge()
        with_tts = getattr(self.tts, "close", None)
        if callable(with_tts):
            with_tts()
        if self.tray is not None:
            self.tray.hide()
        self.overlay.hide()
        self._lock.release()
        log.info("shutdown complete")

    # -------------------------------------------------------------- text input
    def on_submitted(self, text: str) -> None:
        """A message arrived from the input field (typed)."""
        self._respond_to(text, source="typed")

    # ------------------------------------------------------------- voice input
    def on_voice_final(self, text: str) -> None:
        """A command was recognised from speech."""
        text = text.strip()
        if not text:
            return
        log.info("voice command: %r", text)
        self.overlay.set_partial("")
        self._respond_to(text, source="voice")

    def on_voice_state(self, state: str) -> None:
        listening = state == VoiceState.LISTENING.value
        self.overlay.set_listening(listening)
        if state == VoiceState.PROCESSING.value:
            self.overlay.set_voice_status(STATUS_THINKING, "listening")
        elif state == VoiceState.MUTED.value:
            self.overlay.set_muted(True)
        elif state == VoiceState.IDLE.value:
            self.overlay.set_voice_status(STATUS_READY, "idle")

    def on_voice_error(self, message: str) -> None:
        log.warning("voice error: %s", message)
        self.overlay.set_listening(False)  # resets the status line to "ready"...
        self.overlay.set_voice_status(message.splitlines()[0][:80], "error")  # ...so report after
        self.overlay.append_message(message, KIND_SYSTEM)
        if self.tray is not None:
            self.tray.set_listening(False)

    def on_wake(self) -> None:
        self.overlay.set_voice_status("हाँ, बोलिए…", "listening")

    def on_mic_muted(self, muted: bool) -> None:
        self.overlay.set_muted(muted)
        if self.tray is not None:
            self.tray.set_listening(False)
        if not muted:
            self.overlay.set_voice_status(STATUS_READY, "idle")

    def on_mic_toggled(self, listening: bool) -> None:
        """The microphone button: push-to-talk."""
        if listening:
            self.overlay.set_voice_status("माइक खोल रही हूँ…", "listening")
            self.bridge.start(mode="push_to_talk")
            if self.tray is not None:
                self.tray.set_listening(True)
        else:
            self.bridge.stop()
            self.overlay.set_listening(False)
            self.overlay.set_voice_status(STATUS_READY, "idle")
            if self.tray is not None:
                self.tray.set_listening(False)

    def on_mute_toggled(self, muted: bool) -> None:
        self.bridge.set_muted(muted)
        if muted:
            # Muting always ends the listening session, so the microphone button can
            # never stay lit while nothing is being recorded.
            self._end_listening(muted=True)

    def _end_listening(self, muted: bool) -> None:
        """Stop the worker and settle the UI into one honest state."""
        self.bridge.stop()
        self.overlay.set_listening(False)  # also unchecks the microphone button
        if muted:
            self.overlay.set_muted(True)  # ...and re-applies the muted status line
        if self.tray is not None:
            self.tray.set_listening(False)

    # ------------------------------------------------------------- the brain
    def _respond_to(self, text: str, source: str) -> None:
        self.overlay.append_message(text, "user")
        self._persist("user", text)

        reply, question = self.plan_text(text)
        if question is not None:
            self._ask_ai(question, source)
            return
        self._deliver(reply, source)

    def _deliver(self, reply: str, source: str) -> None:
        """Show, store and speak a locally produced answer."""
        self.overlay.append_message(reply, "assistant")
        self._persist("assistant", reply)
        self._speak(reply)
        log.debug("%s command handled: %d chars out", source, len(reply))

    def handle_text(self, text: str) -> str:
        """Route one utterance and return a *local* answer (synchronous callers).

        The chat window uses :meth:`plan_text` instead so a cloud answer can stream in.
        """
        reply, question = self.plan_text(text)
        if question is not None:
            # Offline/text-only caller: fall back to the local engine, never to silence.
            return self.assistant.respond(text).text
        return reply or "ठीक है।"

    def plan_text(self, text: str) -> tuple[str, str | None]:
        """Route one utterance.

        Returns ``(reply, question)``: exactly one of the two is set. ``reply`` is the
        finished local answer; ``question`` means "ask the language model this, stream it
        into the chat". Local commands always win - the model is only consulted when the
        router has no idea what was said *and* there is nothing local to say.
        """
        consent = consent_intent(text)
        if consent is not None:
            reply = self.ai.apply_consent(consent)
            self._save_config()
            self._ai_notice_shown = True
            return reply, None

        if self.confirmation.is_waiting:
            outcome, approved = self.confirmation.resolve(text)
            if outcome is ConfirmationOutcome.APPROVED and approved is not None:
                result = self.executor.execute(approved)
                return result.message or approved.spoken or "ठीक है।", None
            if outcome is ConfirmationOutcome.DECLINED:
                return "ठीक है, रद्द कर दिया।", None
            if outcome is ConfirmationOutcome.UNCLEAR:
                return "कृपया 'हाँ' या 'नहीं' कहिए।", None

        command = self.router.route(text)

        if command.needs_confirmation:
            self.confirmation.request(command)
            return command.spoken, None

        if command.intent == INTENT_UNKNOWN:
            # A spoken answer means the router already produced an honest reply
            # ("photoshop kholo" -> "यह ऐप इस कंप्यूटर पर नहीं है"). Never override it.
            if command.spoken:
                return command.spoken, None
            if self.ai.ready:
                return "", text
            self._note_ai_availability()
            return self.assistant.respond(text).text, None

        if command.intent in (INTENT_INFO_DATE, INTENT_INFO_TIME):
            return self.assistant.respond(text).text, None

        if command.intent == INTENT_VOICE_STOP:
            self._stop_listening()
            return command.spoken, None

        if command.intent == INTENT_VOICE_SWITCH:
            return self._switch_voice(), None

        result = self.executor.execute(command)
        if not result.ok and result.detail == "not_found" and command.spoken:
            return f"{result.message}", None
        return result.message or command.spoken or "ठीक है।", None

    # ------------------------------------------------------------ cloud answers
    def _ask_ai(self, question: str, source: str) -> None:
        """Hand a question to the worker thread; the chat fills in as chunks arrive."""
        self._ai_source = source
        if self.ai_bridge.ask(question):
            return
        # A request is already running: keep this turn honest with the local answer.
        log.info("AI busy; answering %r locally", question[:40])
        self._deliver(self.assistant.respond(question).text, source)

    def _note_ai_availability(self) -> None:
        """One Hindi notice per session when the key exists but consent is missing."""
        if self._ai_notice_shown or self.ai.status() != STATUS_CONSENT:
            return
        self._ai_notice_shown = True
        self.overlay.append_message(self.ai.status_message(), KIND_SYSTEM)

    def on_ai_partial(self, chunk: str) -> None:
        if not self.overlay.is_streaming:
            self.overlay.begin_stream_message()
        self.overlay.stream_chunk(chunk)

    def on_ai_final(self, text: str) -> None:
        """Close the streaming bubble (or add one) and finish the turn."""
        if self.overlay.is_streaming:
            final = self.overlay.finish_stream_message() or text
        else:
            final = text
            if final:
                self.overlay.append_message(final, "assistant")
        if not final:
            return
        self._persist("assistant", final)
        self._speak(final)
        log.debug("AI answer delivered: %d chars", len(final))

    def on_ai_error(self, message: str, code: str) -> None:
        log.warning("AI error (%s): %s", code, message)
        if self.overlay.is_streaming:
            self.overlay.cancel_stream_message()
        role = KIND_SYSTEM if code in _AI_STATUS_CODES else "assistant"
        self.overlay.append_message(message, role)

    def on_ai_cancelled(self) -> None:
        if self.overlay.is_streaming:
            self.overlay.cancel_stream_message()

    def _cancel_ai(self) -> None:
        self.ai_bridge.cancel()

    def _stop_listening(self) -> None:
        self.bridge.set_muted(True)
        self._end_listening(muted=True)

    def _switch_voice(self) -> str:
        options = tts_module.voice_options(self.config.tts.piper_model, self.paths.models)
        chosen = tts_module.next_voice(self.config.tts.voice, options)
        if chosen is None:
            return (
                "इस कंप्यूटर पर कोई हिन्दी आवाज़ नहीं मिली। Windows में हिन्दी भाषा जोड़िए "
                "या Piper आवाज़ डाउनलोड कीजिए।"
            )
        self.config.tts.voice = chosen
        self._save_config()
        self.tts = tts_module.create_engine(
            engine=self.config.tts.engine,
            voice=chosen,
            rate=self.config.tts.rate,
            volume=self.config.tts.volume,
            configured_piper=self.config.tts.piper_model,
            models_dir=self.paths.models,
        )
        return f"अब मैं {chosen} आवाज़ में बोलूँगी।"

    def _speak(self, text: str) -> None:
        if not self.config.tts.speak_replies:
            return
        tts_module.speak_safely(self.tts, text)

    def _save_config(self) -> None:
        try:
            self.config.save(self.paths.config_file)
        except OSError as exc:
            log.warning("could not save settings: %s", exc)

    # ------------------------------------------------------------------ slots
    def on_tray_activated(self) -> None:
        self.overlay.toggle()

    def on_activation_requested(self) -> None:
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
    def _detach_bridge(self) -> None:
        """Break the controller <-> bridge signal cycle before Qt tears anything down.

        Without this the bridge (a QObject) can be collected *after* the QApplication is
        gone, which aborts the interpreter on some PySide6 builds.
        """
        for signal, slot in (
            (self.bridge.final, self.on_voice_final),
            (self.bridge.partial, self.overlay.set_partial),
            (self.bridge.state_changed, self.on_voice_state),
            (self.bridge.error, self.on_voice_error),
            (self.bridge.wake, self.on_wake),
            (self.bridge.muted, self.on_mic_muted),
            (self.ai_bridge.partial, self.on_ai_partial),
            (self.ai_bridge.final, self.on_ai_final),
            (self.ai_bridge.error, self.on_ai_error),
            (self.ai_bridge.cancelled, self.on_ai_cancelled),
        ):
            with contextlib.suppress(RuntimeError, TypeError):
                signal.disconnect(slot)
        self.bridge.deleteLater()

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
