"""Qt bridge for timers.

``AlarmTimer`` fires on its own thread, so the announcement is delivered through a Qt
signal: the slot then runs on the GUI thread, where touching widgets is legal. Same
pattern as :mod:`shraddha.ui.voice` and :mod:`shraddha.ui.ai`.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from shraddha.commands.timer import AlarmTimer
from shraddha.logging_setup import get_logger

log = get_logger("ui.timer")


class TimerBridge(QObject):
    """Exposes :class:`~shraddha.commands.timer.AlarmTimer` to the controller."""

    fired = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._timer = AlarmTimer(on_fire=self._announce)

    # ------------------------------------------------------------------ state
    @property
    def is_running(self) -> bool:
        return self._timer.is_running

    def remaining(self) -> float:
        return self._timer.remaining()

    # --------------------------------------------------------------- commands
    def start(self, seconds: int) -> str:
        return self._timer.start(int(seconds))

    def cancel(self) -> str:
        return self._timer.cancel()

    def status(self) -> str:
        return self._timer.status()

    def close(self) -> None:
        self._timer.close()

    # ---------------------------------------------------------------- internal
    def _announce(self, label: str) -> None:
        """Called on the timer thread - emitting is thread-safe, the slot is queued."""
        log.debug("timer fired: %s", label)
        self.fired.emit(label)


__all__ = ["TimerBridge"]
