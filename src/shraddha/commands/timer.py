"""Timers that live for one phrase and then announce themselves.

Small on purpose: one timer at a time (starting a new one replaces the old, and says so),
a `threading.Timer` instead of a polling loop, and an injected callback so the Qt layer
decides how the announcement is shown and spoken.

The callback runs on the timer's thread. That is deliberate: the caller is responsible for
marshalling it to the GUI thread (see :class:`shraddha.ui.timer.TimerBridge`), so this
module stays free of Qt - which keeps it testable in microseconds.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from shraddha.logging_setup import get_logger

log = get_logger("timer")


def _default_scheduler(delay: float, callback: Callable[[], None]) -> threading.Timer:
    """A daemon timer, so a pending timer can never keep the process alive at exit."""
    handle = threading.Timer(delay, callback)
    handle.daemon = True
    return handle


def hindi_duration(seconds: int) -> str:
    """A short Hindi duration: 90 -> "1 मिनट 30 सेकंड"."""
    seconds = max(0, int(seconds))
    if seconds >= 3_600:
        hours, rest = divmod(seconds, 3_600)
        minutes = rest // 60
        return f"{hours} घंटे" if not minutes else f"{hours} घंटे {minutes} मिनट"
    if seconds >= 60:
        minutes, rest = divmod(seconds, 60)
        return f"{minutes} मिनट" if not rest else f"{minutes} मिनट {rest} सेकंड"
    return f"{seconds} सेकंड"


@dataclass
class AlarmTimer:
    """One active timer, announced through ``on_fire``."""

    on_fire: Callable[[str], None]
    #: Injectable for tests: ``scheduler(delay_s, callback) -> handle`` with ``.cancel()``.
    scheduler: Callable[[float, Callable[[], None]], object] = _default_scheduler
    clock: Callable[[], float] = time.monotonic
    _handle: object | None = field(default=None, init=False, repr=False)
    _label: str = field(default="", init=False)
    _deadline: float = field(default=0.0, init=False)

    # ------------------------------------------------------------------ state
    @property
    def is_running(self) -> bool:
        return self._handle is not None

    @property
    def label(self) -> str:
        return self._label

    def remaining(self) -> float:
        """Seconds left, or ``0.0`` when no timer is armed."""
        if self._handle is None:
            return 0.0
        return max(0.0, self._deadline - self.clock())

    # --------------------------------------------------------------- commands
    def start(self, seconds: int, label: str | None = None) -> str:
        """Arm the timer, replacing any previous one. Returns the Hindi confirmation."""
        seconds = max(1, int(seconds))
        replaced = self.is_running
        self._cancel_handle()
        self._label = label or hindi_duration(seconds)
        self._deadline = self.clock() + seconds
        try:
            handle = self.scheduler(float(seconds), self._fire)
        except Exception as exc:  # pragma: no cover - only a broken threading module
            log.warning("could not start timer: %s", exc)
            self._handle = None
            return "टाइमर शुरू नहीं हो सका।"
        start = getattr(handle, "start", None)
        if callable(start):
            start()
        self._handle = handle
        log.info("timer armed for %ss (%s)", seconds, self._label)
        prefix = "पिछला टाइमर हटाकर " if replaced else ""
        return f"{prefix}{self._label} का टाइमर लगा दिया।"

    def cancel(self) -> str:
        if not self.is_running:
            return "कोई टाइमर नहीं चल रहा था।"
        label = self._label
        self._cancel_handle()
        log.info("timer cancelled (%s)", label)
        return f"{label} का टाइमर रद्द कर दिया।"

    def status(self) -> str:
        if not self.is_running:
            return "अभी कोई टाइमर नहीं चल रहा।"
        return f"{self._label} का टाइमर चल रहा है, लगभग {self._remaining_label()} बाकी।"

    def close(self) -> None:
        """Drop the timer without announcing anything (shutdown path)."""
        self._cancel_handle()

    # ---------------------------------------------------------------- internal
    def _fire(self) -> None:
        label, self._handle = self._label, None
        self._label, self._deadline = "", 0.0
        log.info("timer fired (%s)", label)
        try:
            self.on_fire(label)
        except Exception as exc:  # a UI callback must never kill the thread
            log.warning("timer callback failed: %s", exc)

    def _cancel_handle(self) -> None:
        handle, self._handle = self._handle, None
        cancel = getattr(handle, "cancel", None)
        if callable(cancel):
            try:
                cancel()
            except Exception as exc:  # pragma: no cover - teardown
                log.debug("timer cancel failed: %s", exc)

    def _remaining_label(self) -> str:
        remaining = round(self.remaining())
        return hindi_duration(remaining) if remaining > 0 else "कुछ सेकंड"


__all__ = ["AlarmTimer", "hindi_duration"]
