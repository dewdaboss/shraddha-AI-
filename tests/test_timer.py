"""Phase 4 - the timer: armed, replaced, fired, cancelled.

The scheduler is a fake, so no real thread is started and nothing waits. What is verified
is the behaviour the user experiences: one timer at a time, a Hindi confirmation, and an
announcement when it runs out.
"""

from __future__ import annotations

import threading

import pytest

from shraddha.commands.timer import AlarmTimer, hindi_duration


class FakeHandle:
    def __init__(self, delay: float, callback) -> None:
        self.delay = delay
        self.callback = callback
        self.cancelled = False
        self.started = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True


class FakeScheduler:
    def __init__(self) -> None:
        self.handles: list[FakeHandle] = []

    def __call__(self, delay: float, callback) -> FakeHandle:
        handle = FakeHandle(delay, callback)
        self.handles.append(handle)
        return handle


@pytest.fixture()
def fired() -> list[str]:
    return []


@pytest.fixture()
def scheduler() -> FakeScheduler:
    return FakeScheduler()


@pytest.fixture()
def timer(fired: list[str], scheduler: FakeScheduler) -> AlarmTimer:
    return AlarmTimer(on_fire=fired.append, scheduler=scheduler, clock=lambda: 1_000.0)


# ------------------------------------------------------------------- durations
@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (5, "5 सेकंड"),
        (60, "1 मिनट"),
        (90, "1 मिनट 30 सेकंड"),
        (3_600, "1 घंटे"),
        (5_400, "1 घंटे 30 मिनट"),
        (0, "0 सेकंड"),
    ],
)
def test_hindi_duration(seconds: int, expected: str) -> None:
    assert hindi_duration(seconds) == expected


# --------------------------------------------------------------------- arming
def test_starting_a_timer_schedules_and_confirms(timer: AlarmTimer, scheduler: FakeScheduler) -> None:
    message = timer.start(300)

    assert scheduler.handles[0].delay == 300.0
    assert scheduler.handles[0].started is True
    assert timer.is_running is True
    assert "5 मिनट" in message
    assert timer.label == "5 मिनट"


def test_remaining_counts_down(timer: AlarmTimer) -> None:
    timer.start(300)
    assert timer.remaining() == 300.0

    timer.clock = lambda: 1_120.0  # 120 s later
    assert timer.remaining() == 180.0


def test_only_one_timer_at_a_time(timer: AlarmTimer, scheduler: FakeScheduler) -> None:
    timer.start(300)
    message = timer.start(60)

    assert scheduler.handles[0].cancelled is True, "the old timer must be dropped"
    assert timer.label == "1 मिनट"
    assert "पिछला" in message


def test_starting_twice_never_leaves_two_timers(timer: AlarmTimer, scheduler: FakeScheduler) -> None:
    timer.start(60)
    timer.start(120)
    timer.start(180)
    assert [handle.cancelled for handle in scheduler.handles] == [True, True, False]
    assert timer.is_running is True


# ---------------------------------------------------------------------- firing
def test_firing_announces_once_and_disarms(timer: AlarmTimer, fired: list[str], scheduler) -> None:
    timer.start(120)
    scheduler.handles[0].callback()

    assert fired == ["2 मिनट"]
    assert timer.is_running is False
    assert timer.remaining() == 0.0


def test_a_broken_callback_does_not_break_the_timer(fired: list[str], scheduler) -> None:
    broken = AlarmTimer(on_fire=lambda _label: (_ for _ in ()).throw(RuntimeError("ui gone")),
                        scheduler=scheduler)
    broken.start(5)
    scheduler.handles[0].callback()  # must not raise
    assert broken.is_running is False


def test_fire_after_cancel_does_nothing(timer: AlarmTimer, fired: list[str], scheduler) -> None:
    timer.start(60)
    timer.cancel()
    assert timer.is_running is False
    assert fired == []


# -------------------------------------------------------------------- cancel
def test_cancel_reports_what_it_did(timer: AlarmTimer, scheduler: FakeScheduler) -> None:
    assert "नहीं चल रहा" in timer.cancel()

    timer.start(60)
    assert "रद्द" in timer.cancel()
    assert scheduler.handles[0].cancelled is True
    assert timer.is_running is False


def test_status_text(timer: AlarmTimer) -> None:
    assert "नहीं चल रहा" in timer.status()
    timer.start(300)
    timer.clock = lambda: 1_060.0
    status = timer.status()
    assert "5 मिनट" in status
    assert "4 मिनट" in status


def test_close_is_silent(timer: AlarmTimer, fired: list[str], scheduler: FakeScheduler) -> None:
    timer.start(60)
    timer.close()
    assert scheduler.handles[0].cancelled is True
    assert timer.is_running is False
    assert fired == []


# ------------------------------------------------------------------ the default
def test_the_default_scheduler_uses_daemon_threads() -> None:
    """A pending timer must never keep the process alive after quit."""
    timer = AlarmTimer(on_fire=lambda _label: None)
    timer.start(600)
    handle = timer._handle
    try:
        assert isinstance(handle, threading.Timer)
        assert handle.daemon is True
    finally:
        timer.close()


def test_a_scheduler_that_raises_is_reported() -> None:
    def broken(_delay: float, _callback) -> object:
        raise RuntimeError("no threads for you")

    timer = AlarmTimer(on_fire=lambda _label: None, scheduler=broken)
    assert "नहीं हो सका" in timer.start(60)
    assert timer.is_running is False
