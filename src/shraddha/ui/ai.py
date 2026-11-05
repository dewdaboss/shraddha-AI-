"""Qt bridge for cloud answers.

The network call runs on a worker thread so the window never freezes while Google
thinks. Same contract as :class:`shraddha.ui.voice.VoiceBridge`:

* **worker thread** owns the ``AiService`` generator and consumes it;
* **GUI thread** receives ``partial`` / ``final`` / ``error`` through queued Qt signals.

Only one request is in flight at a time. A second request while busy is refused (the
controller answers it from the local engine) instead of queueing a thumbnail of the
user's questions in memory.

**Nothing here acts on the computer.** The bridge carries text into the chat view and
nothing else: no command objects, no executor, no shell.
"""

from __future__ import annotations

import contextlib
import threading

from PySide6.QtCore import QObject, Signal

from shraddha.ai.service import AiService
from shraddha.logging_setup import get_logger

log = get_logger("ui.ai")

CANCELLED_SUFFIX = " …"


class AiBridge(QObject):
    """Streams :meth:`AiService.ask` into Qt signals."""

    partial = Signal(str)
    final = Signal(str)
    error = Signal(str, str)  # message, code
    cancelled = Signal()
    started = Signal()

    def __init__(self, service: AiService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._busy = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ state
    @property
    def service(self) -> AiService:
        return self._service

    @property
    def is_busy(self) -> bool:
        return self._busy

    def status(self) -> str:
        return self._service.status()

    # --------------------------------------------------------------- commands
    def ask(self, text: str) -> bool:
        """Start a request. Returns False when one is already running."""
        with self._lock:
            if self._busy:
                log.debug("AI request ignored: one is already running")
                return False
            self._busy = True
            self._cancel.clear()
            self._thread = threading.Thread(
                target=self._run, args=(text,), name="shraddha-ai", daemon=True
            )
            self._thread.start()
        self.started.emit()
        return True

    def cancel(self) -> None:
        """Ask the worker to stop; it exits at the next chunk boundary."""
        self._cancel.set()

    def wait(self, timeout: float = 2.0) -> None:
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    def shutdown(self) -> None:
        self.cancel()
        self.wait()
        self._service.close()

    # ---------------------------------------------------------------- threads
    def _run(self, text: str) -> None:
        stream = None
        stopped = False
        try:
            stream = self._service.ask(text)
            for event in stream:
                if self._cancel.is_set():
                    stopped = True
                    break
                if event.kind == "partial":
                    self.partial.emit(event.text)
                elif event.kind == "final":
                    self.final.emit(event.text)
                    return
                elif event.kind == "error":
                    self.error.emit(event.text, event.detail)
                    return
        except Exception as exc:
            log.exception("AI worker failed")
            self.error.emit(f"क्लाउड AI में गड़बड़ी: {exc}", "ai_error")
        finally:
            with contextlib.suppress(Exception):
                if stream is not None:
                    stream.close()  # type: ignore[union-attr]
            self._busy = False
            if stopped or self._cancel.is_set():
                self.cancelled.emit()


__all__ = ["CANCELLED_SUFFIX", "AiBridge"]
