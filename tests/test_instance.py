"""Tests for the single-instance lock, including stale-lock recovery."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from shraddha.instance import SingleInstanceLock, process_is_running


def test_acquire_creates_lock_file_with_pid(tmp_path: Path) -> None:
    lock = SingleInstanceLock(tmp_path / "sub" / "app.lock")
    assert lock.acquire() is True
    assert lock.is_held is True
    assert lock.path.read_text(encoding="utf-8").strip() == str(os.getpid())
    lock.release()


def test_second_instance_cannot_acquire(tmp_path: Path) -> None:
    path = tmp_path / "app.lock"
    first = SingleInstanceLock(path)
    second = SingleInstanceLock(path)
    assert first.acquire() is True
    assert second.acquire() is False, "a live instance must block a second one"
    assert second.is_held is False
    first.release()


def test_release_allows_a_later_instance(tmp_path: Path) -> None:
    path = tmp_path / "app.lock"
    first = SingleInstanceLock(path)
    first.acquire()
    first.release()
    assert not path.exists()
    assert SingleInstanceLock(path).acquire() is True


def test_stale_lock_from_a_dead_process_is_reclaimed(tmp_path: Path) -> None:
    path = tmp_path / "app.lock"
    path.write_text("999999999\n", encoding="utf-8")  # a pid that cannot exist
    lock = SingleInstanceLock(path)
    assert lock.acquire() is True
    assert path.read_text(encoding="utf-8").strip() == str(os.getpid())


@pytest.mark.parametrize("content", ["", "not-a-pid", "\n\n"])
def test_unreadable_lock_is_treated_as_stale(tmp_path: Path, content: str) -> None:
    path = tmp_path / "app.lock"
    path.write_text(content, encoding="utf-8")
    assert SingleInstanceLock(path).acquire() is True


def test_release_does_not_delete_another_processes_lock(tmp_path: Path) -> None:
    path = tmp_path / "app.lock"
    path.write_text("999999999\n", encoding="utf-8")
    lock = SingleInstanceLock(path)
    lock.release()  # not held by us at all
    assert path.exists(), "release() must not remove a lock this object never took"


def test_context_manager_releases_on_exit(tmp_path: Path) -> None:
    path = tmp_path / "app.lock"
    with SingleInstanceLock(path):
        assert path.exists()
    assert not path.exists()


def test_context_manager_raises_when_busy(tmp_path: Path) -> None:
    path = tmp_path / "app.lock"
    holder = SingleInstanceLock(path)
    holder.acquire()
    with pytest.raises(RuntimeError, match="already running"), SingleInstanceLock(path):
        pass
    holder.release()


def test_process_is_running_for_self_and_init() -> None:
    assert process_is_running(os.getpid()) is True
    assert process_is_running(0) is False
    assert process_is_running(-5) is False


def test_process_is_running_for_impossible_pid() -> None:
    assert process_is_running(999_999_999) is False
