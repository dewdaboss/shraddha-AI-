"""Single-instance guarantee.

Two mechanisms, because one is not enough:

1. :class:`SingleInstanceLock` - an exclusive lock file with stale-lock recovery. Pure
   standard library, so it works even when Qt cannot start.
2. Qt's ``QLocalServer`` (in :mod:`shraddha.ui.ipc`) - lets a second launch *wake up*
   the instance that is already running instead of dying silently.

A crash or a ``kill -9`` leaves a stale lock file behind, so liveness of the recorded
PID is verified before the lock is believed.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import sys
from pathlib import Path
from types import TracebackType

from shraddha.logging_setup import get_logger

log = get_logger("instance")

#: Set when a lock is believed to be stale but the OS refuses to let us replace it.
_MAX_ATTEMPTS = 2


def process_is_running(pid: int) -> bool:
    """Best-effort liveness check for ``pid``.

    Errs on the side of "running": a false positive merely refuses to start a second
    instance (annoying), while a false negative lets two assistants fight over the
    microphone and the hotkey (worse).
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _windows_process_is_running(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _windows_process_is_running(pid: int) -> bool:
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    kernel32 = getattr(ctypes, "windll", None)
    if kernel32 is None:  # not actually Windows (e.g. a mocked sys.platform in tests)
        return True
    handle = kernel32.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == STILL_ACTIVE
    finally:
        kernel32.kernel32.CloseHandle(handle)


class SingleInstanceLock:
    """Exclusive, stale-aware lock file.

    Usage::

        lock = SingleInstanceLock(paths.lock_file)
        if not lock.acquire():
            ...  # another instance owns it
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._held = False

    @property
    def is_held(self) -> bool:
        return self._held

    def acquire(self) -> bool:
        """Try to take the lock. Returns ``False`` if another live instance holds it."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("cannot create lock directory %s: %s", self.path.parent, exc)
            return False

        for _ in range(_MAX_ATTEMPTS):
            if self._create():
                return True
            if not self._break_if_stale():
                return False
        return False

    def release(self) -> None:
        """Release the lock, but only if this process still owns the file."""
        if not self._held:
            return
        try:
            if self._read_pid() in (os.getpid(), None):
                self.path.unlink(missing_ok=True)
        except OSError as exc:
            log.debug("could not remove lock file %s: %s", self.path, exc)
        finally:
            self._held = False

    # ------------------------------------------------------------------ helpers
    def _create(self) -> bool:
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return False
        except OSError as exc:
            log.warning("cannot create lock file %s: %s", self.path, exc)
            return False

        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(f"{os.getpid()}\n")
        except OSError as exc:
            log.warning("cannot write lock file %s: %s", self.path, exc)
            with contextlib.suppress(OSError):
                self.path.unlink(missing_ok=True)
            return False

        self._held = True
        log.debug("instance lock acquired: %s (pid %s)", self.path, os.getpid())
        return True

    def _read_pid(self) -> int | None:
        try:
            raw = self.path.read_text(encoding="utf-8").strip().splitlines()
        except (OSError, UnicodeDecodeError):
            return None
        if not raw:
            return None
        try:
            return int(raw[0])
        except ValueError:
            return None

    def _break_if_stale(self) -> bool:
        """Remove the lock file if its owner is gone. Returns True if removed."""
        pid = self._read_pid()
        if pid is not None and process_is_running(pid):
            # Deliberately not special-casing our own PID: two live holders inside one
            # process is a bug we want to fail loudly, not to paper over.
            log.info("another instance is already running (pid %s)", pid)
            return False

        # Unreadable or dead: assume stale. An empty/partial file can be a crash
        # between create() and write(), so treat it as stale too.
        log.info("removing stale instance lock (pid %s)", pid)
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("cannot remove stale lock %s: %s", self.path, exc)
            return False
        return True

    # ------------------------------------------------------------- context mgmt
    def __enter__(self) -> SingleInstanceLock:
        if not self.acquire():
            raise RuntimeError("another SHRADDHA AI instance is already running")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()
