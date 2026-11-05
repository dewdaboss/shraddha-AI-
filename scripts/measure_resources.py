"""Measure startup time and resident memory of SHRADDHA AI.

Run it on the machine you care about - the numbers are only meaningful for that machine:

    python scripts/measure_resources.py
    python scripts/measure_resources.py --seconds 6 --json

It reports:

* **import cost** - what loading the core costs versus loading the Qt UI;
* **startup** - wall-clock time from process spawn to "UI ready";
* **resident memory** - sampled while the interface is up, plus the peak.

The UI is started with ``--smoke``, which builds the real window, proves it is alive and
then exits, so nothing is left running.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
READY_MARKER = "SHRADDHA_UI_READY"
IS_WINDOWS = sys.platform == "win32"


def child_env() -> dict[str, str]:
    env = os.environ.copy()
    # Never touch the developer's real settings or history.
    env["SHRADDHA_HOME"] = tempfile.mkdtemp(prefix="shraddha-measure-")
    if sys.platform.startswith("linux") and not env.get("DISPLAY"):
        env.setdefault("QT_QPA_PLATFORM", "minimal")
    return env


def rss_bytes(pid: int) -> int | None:
    """Resident set size of ``pid`` in bytes, using only the standard library."""
    try:
        if IS_WINDOWS:
            return _windows_rss(pid)
        status = Path(f"/proc/{pid}/status")
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _windows_rss(pid: int) -> int | None:
    import ctypes
    from ctypes import wintypes

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(ProcessMemoryCounters)
        if not ctypes.windll.psapi.GetProcessMemoryInfo(  # type: ignore[attr-defined]
            handle, ctypes.byref(counters), counters.cb
        ):
            return None
        return int(counters.WorkingSetSize)
    finally:
        kernel32.CloseHandle(handle)


def measure_import(module: str | None) -> float:
    """Milliseconds to import ``module`` (``None`` = bare interpreter baseline).

    Run twice and keep the best, so a cold page cache does not masquerade as import
    cost. The bare-interpreter run is reported alongside so callers can subtract it.
    """
    best = float("inf")
    code = "pass" if module is None else f"import {module}"
    env = child_env()
    for _ in range(2):
        started = time.perf_counter()
        subprocess.run(
            [sys.executable, "-c", code],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        best = min(best, (time.perf_counter() - started) * 1000)
    return best


def measure_ui(seconds: float, interval: float = 0.02) -> dict[str, object]:
    """Spawn the UI, wait for the ready marker, then sample memory until it exits."""
    process = subprocess.Popen(
        [sys.executable, "-m", "shraddha", "--smoke", f"{seconds}"],
        cwd=str(REPO_ROOT),
        env=child_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    ready = threading.Event()
    markers: list[str] = []

    def read_stdout() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            markers.append(line.strip())
            if READY_MARKER in line:
                ready.set()

    reader = threading.Thread(target=read_stdout, daemon=True)
    reader.start()

    started = time.perf_counter()
    ready.wait(timeout=max(30.0, seconds + 25.0))
    startup_ms = (time.perf_counter() - started) * 1000

    samples: list[int] = []
    peak = 0
    while process.poll() is None:
        value = rss_bytes(process.pid)
        if value:
            samples.append(value)
            peak = max(peak, value)
        time.sleep(interval)

    stderr = process.stderr.read() if process.stderr is not None else ""
    steady = statistics.median(samples[len(samples) // 4 :]) if samples else 0
    return {
        "startup_ms": round(startup_ms, 1),
        "ready": READY_MARKER in "".join(markers),
        "exit_code": process.returncode,
        "rss_median_mb": round(steady / 1024**2, 1),
        "rss_peak_mb": round(peak / 1024**2, 1),
        "samples": len(samples),
        "stderr_tail": stderr.strip().splitlines()[-3:] if stderr.strip() else [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure SHRADDHA AI resource usage.")
    parser.add_argument("--seconds", type=float, default=4.0, help="how long to keep the UI up")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    baseline = measure_import(None)
    core_import = measure_import("shraddha.doctor")
    ui_import = measure_import("shraddha.ui.app")
    ui = measure_ui(args.seconds)

    report = {
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "python": platform.python_version(),
        "interpreter_baseline_ms": round(baseline, 1),
        "import_core_ms": round(core_import - baseline, 1),
        "import_ui_ms": round(ui_import - baseline, 1),
        **ui,
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"SHRADDHA AI resource report — {report['platform']}")
        print(f"python            {report['python']}")
        print(
            f"bare interpreter  {report['interpreter_baseline_ms']:>8.1f} ms   (baseline, subtracted below)"
        )
        print(f"import core       {report['import_core_ms']:>8.1f} ms   (doctor, config, storage)")
        print(f"import Qt UI      {report['import_ui_ms']:>8.1f} ms")
        print(f"startup to ready  {report['startup_ms']:>8.1f} ms")
        print(
            f"resident (median) {report['rss_median_mb']:>8.1f} MB   over {report['samples']} samples"
        )
        print(f"resident (peak)   {report['rss_peak_mb']:>8.1f} MB")
        print(f"exit code          {report['exit_code']}")
        if not report["ready"]:
            print("WARNING: the UI never reported readiness", file=sys.stderr)
            for line in report["stderr_tail"]:
                print(f"  {line}", file=sys.stderr)
        print()
        print("note: this sandbox runs Qt's 'minimal' platform with stub GL/D-Bus libraries")
        print("and no system fonts, so these numbers are indicative, not a Windows result.")

    return 0 if report["ready"] and report["exit_code"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
