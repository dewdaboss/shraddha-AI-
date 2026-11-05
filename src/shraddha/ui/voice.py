"""Qt bridge for the voice pipeline.

Threading contract:

* **worker thread** - owns ``VoiceService``. It opens the microphone, drains audio
  frames, runs the VAD and (crucially) the ASR, so a 1-3 second model load or a slow
  decode never freezes the interface;
* **audio callback** (PortAudio's own thread) - only pushes bytes into a queue;
* **GUI thread** - receives Qt signals. Emitting from the worker thread is safe: Qt
  queues the call because the receiver lives in the GUI thread.

No polling timers, no busy loops: the worker blocks on a queue with a 100 ms timeout.
"""

from __future__ import annotations

import contextlib
import queue
import threading

from PySide6.QtCore import QObject, Signal

from shraddha.logging_setup import get_logger
from shraddha.speech.service import VoiceEvent, VoiceService, VoiceState

log = get_logger("ui.voice")

_QUEUE_TIMEOUT_S = 0.1


class VoiceBridge(QObject):
    """Exposes :class:`VoiceService` as Qt signals, on its own thread."""

    state_changed = Signal(str)
    partial = Signal(str)
    final = Signal(str)
    error = Signal(str)
    wake = Signal()
    muted = Signal(bool)
    model_loaded = Signal(str)

    def __init__(self, service: VoiceService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._frames: queue.Queue[bytes] = queue.Queue(maxsize=200)
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._mode = service.mode
        self._live = False

    # ------------------------------------------------------------------ state
    @property
    def service(self) -> VoiceService:
        return self._service

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def is_muted(self) -> bool:
        return self._service.is_muted

    @property
    def state(self) -> VoiceState:
        return self._service.state

    # --------------------------------------------------------------- commands
    def start(self, mode: str | None = None) -> None:
        """Begin listening. Model loading happens on the worker thread."""
        if mode:
            self._mode = mode
        if self.is_running:
            return
        self._stopping.clear()
        self._drain_frames()
        self._thread = threading.Thread(target=self._run, name="shraddha-voice", daemon=True)
        self._thread.start()
        self._live = True
        log.debug("voice bridge started (mode=%s)", self._mode)

    def stop(self, timeout: float = 2.0) -> None:
        """Stop listening and wait for the worker to finish."""
        self._live = False
        self._stopping.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
            if thread.is_alive():  # pragma: no cover - only on a wedged driver
                log.warning("voice worker did not stop within %.1fs", timeout)
        self._drain_frames()

    def toggle_mute(self) -> None:
        self._emit_all(self._service.toggle_mute())

    def set_muted(self, muted: bool) -> None:
        self._emit_all(self._service.set_muted(muted))

    def shutdown(self) -> None:
        self.stop()
        self._service.close()

    # ---------------------------------------------------------------- threads
    def _run(self) -> None:
        try:
            self._emit_all(self._service.start(self._mode))
            while not self._stopping.is_set():
                try:
                    frame = self._frames.get(timeout=_QUEUE_TIMEOUT_S)
                except queue.Empty:
                    self._emit_all(self._service.tick())
                    continue
                self._emit_all(self._service.feed(frame))
                if self._service.has_pending_segments:
                    self._emit_all(self._service.process_pending())
        except Exception as exc:  # a backend crash must not kill the app silently
            log.exception("voice worker failed")
            with contextlib.suppress(Exception):
                self.error.emit(f"आवाज़ सेवा में गड़बड़ी: {exc}")
        finally:
            with contextlib.suppress(Exception):
                self._emit_all(self._service.stop())

    def _on_frame(self, pcm: bytes) -> None:
        """Called on PortAudio's thread. Must never block or raise."""
        if not self._live:
            return
        try:
            self._frames.put_nowait(pcm)
        except queue.Full:
            # Dropping a frame is better than stalling the audio device.
            log.debug("audio queue full, dropping a frame")

    def _drain_frames(self) -> None:
        while True:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                return

    # ----------------------------------------------------------------- events
    def _emit_all(self, events: list[VoiceEvent]) -> None:
        """Translate service events into signals (idempotent, order preserving)."""
        for event in events:
            self._dispatch(event)

    def _dispatch(self, event: VoiceEvent) -> None:
        kind = event.kind
        if kind == "state":
            self.state_changed.emit(event.text)
        elif kind == "partial":
            self.partial.emit(event.text)
        elif kind == "final":
            self.final.emit(event.text)
        elif kind == "wake":
            self.wake.emit()
        elif kind == "error":
            self.error.emit(event.text)
        elif kind == "muted":
            self.muted.emit(event.text == "muted")
        elif kind == "model_loaded":
            self.model_loaded.emit(event.text)
        else:
            log.debug("voice event %s: %s", kind, event.text)
