"""Environment and capability diagnostics (``python -m shraddha --doctor``).

Answers the question a desktop assistant must always be able to answer:
*why can't it hear me / why is it silent?* Every check is cheap, read-only and works
without installing any optional dependency.
"""

from __future__ import annotations

import ctypes
import importlib.util
import os
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path

from shraddha import __version__
from shraddha.config import AppConfig, ConfigError
from shraddha.logging_setup import get_logger
from shraddha.paths import Paths, get_paths
from shraddha.speech import audio as audio_module
from shraddha.speech import tts
from shraddha.speech.engines import engine_report

log = get_logger("doctor")

#: Optional extras and the module that proves each one is installed.
OPTIONAL_EXTRAS: dict[str, tuple[str, ...]] = {
    "ui (PySide6)": ("PySide6",),
    "audio (sounddevice)": ("sounddevice",),
    "asr (sherpa-onnx)": ("sherpa_onnx",),
    "asr-vosk (vosk)": ("vosk",),
    "tts-piper (piper)": ("piper",),
    "win (pywin32)": ("win32com",),
}

#: 4 GB is the supported floor; the LLM needs 8 GB.
RAM_FLOOR_GB = 4
RAM_LLM_GB = 8


@dataclass(slots=True)
class DoctorReport:
    """Everything the doctor found, ready to print as text or emit as JSON."""

    version: str = __version__
    python: str = ""
    platform: str = ""
    architecture: str = ""
    cpu_count: int = 0
    ram_total_gb: float | None = None
    ram_available_gb: float | None = None
    paths: dict[str, str] = field(default_factory=dict)
    writable: bool = False
    config_path: str = ""
    config_ok: bool = True
    db_version: int = 0
    extras: dict[str, bool] = field(default_factory=dict)
    models: dict[str, bool] = field(default_factory=dict)
    voices: list[str] = field(default_factory=list)
    engines: dict[str, bool] = field(default_factory=dict)
    selected_engine: str = tts.NONE
    microphone: dict[str, object] = field(default_factory=dict)
    asr_engines: dict[str, dict[str, object]] = field(default_factory=dict)
    wake_mode: str = ""
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "python": self.python,
            "platform": self.platform,
            "architecture": self.architecture,
            "cpu_count": self.cpu_count,
            "ram_total_gb": self.ram_total_gb,
            "ram_available_gb": self.ram_available_gb,
            "paths": self.paths,
            "writable": self.writable,
            "config_path": self.config_path,
            "config_ok": self.config_ok,
            "db_version": self.db_version,
            "extras": self.extras,
            "models": self.models,
            "voices": self.voices,
            "engines": self.engines,
            "selected_engine": self.selected_engine,
            "microphone": self.microphone,
            "asr_engines": self.asr_engines,
            "wake_mode": self.wake_mode,
            "warnings": self.warnings,
        }

    def to_text(self) -> str:
        mark = {True: "ok  ", False: "MISS"}
        lines = [
            "SHRADDHA AI - environment report",
            "=" * 46,
            f"version          {self.version}",
            f"python           {self.python}",
            f"platform         {self.platform}",
            f"architecture     {self.architecture}",
            f"cpu cores        {self.cpu_count}",
            f"ram              {_fmt_gb(self.ram_total_gb)} total, "
            f"{_fmt_gb(self.ram_available_gb)} available",
            "",
            "paths",
            "-" * 46,
        ]
        for name, value in self.paths.items():
            if name in {"config", "database"}:
                continue  # reported in detail on the next two lines
            lines.append(f"  {name:<14} {value}")
        lines.append(f"  writable       {'yes' if self.writable else 'NO'}")
        lines.append(
            f"  config         {self.config_path} ({'valid' if self.config_ok else 'INVALID'})"
        )
        lines.append(f"  database       schema v{self.db_version}")

        lines += ["", "optional components", "-" * 46]
        for name, present in self.extras.items():
            lines.append(f"  {mark[present]}  {name}")

        lines += ["", "models", "-" * 46]
        for name, present in self.models.items():
            lines.append(f"  {mark[present]}  {name}")

        lines += ["", "hindi voice output", "-" * 46]
        if self.voices:
            lines += [f"  ok    {voice}" for voice in self.voices]
        else:
            lines.append("  MISS  no Hindi voice installed")
        for name, present in self.engines.items():
            lines.append(f"  {mark[present]}  engine: {name}")
        lines.append(
            f"  -> selected: {self.selected_engine} ({tts.describe_engine(self.selected_engine)})"
        )

        lines += ["", "hindi voice input", "-" * 46]
        mic_ok = bool(self.microphone.get("available"))
        lines.append(f"  {mark[mic_ok]}  microphone: {self.microphone.get('reason') or 'ready'}")
        for name, info in self.asr_engines.items():
            ready = bool(info.get("ready"))
            detail = "" if ready else f" - {info.get('message')}"
            lines.append(f"  {mark[ready]}  engine {name}{detail}")
        lines.append(f"       wake word mode: {self.wake_mode or 'unknown'}")

        if self.warnings:
            lines += ["", "warnings", "-" * 46, *(f"  ! {w}" for w in self.warnings)]
        return "\n".join(lines)


def _fmt_gb(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.1f} GB"


def _memory_info() -> tuple[float | None, float | None]:
    """Total and available RAM in GB, using only the standard library."""
    if sys.platform == "win32":
        return _windows_memory()
    return _posix_memory()


def _windows_memory() -> tuple[float | None, float | None]:
    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(MemoryStatusEx)
    try:
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
            return (None, None)
    except (AttributeError, OSError):
        return (None, None)
    return (status.ullTotalPhys / 1024**3, status.ullAvailPhys / 1024**3)


def _posix_memory() -> tuple[float | None, float | None]:
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return (None, None)
    values: dict[str, float] = {}
    try:
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            key, _, rest = line.partition(":")
            if key in {"MemTotal", "MemAvailable"}:
                values[key] = float(rest.strip().split()[0]) / 1024**2  # kB -> GB
    except (OSError, ValueError, IndexError):
        return (None, None)
    return (values.get("MemTotal"), values.get("MemAvailable"))


def _check_writable(paths: Paths) -> bool:
    try:
        paths.ensure()
        probe = paths.cache / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _module_present(names: tuple[str, ...]) -> bool:
    """True when any of the candidate modules can be imported.

    ``find_spec`` inspects the import system without executing the module, so this
    costs microseconds and never loads ONNX Runtime or Qt.
    """
    for name in names:
        try:
            if importlib.util.find_spec(name) is not None:
                return True
        except (ImportError, ValueError):
            continue
    return False


def _check_models(paths: Paths) -> dict[str, bool]:
    return {
        "vosk small-hi (~42 MB)": any(paths.models.glob("**/vosk-model-small-hi*")),
        "indicconformer hi int8 (~130 MB)": any(paths.models.glob("**/hi/model.int8.onnx"))
        or any(paths.models.glob("**/indicconformer*/**/model*.onnx")),
        "piper hi_IN voice (~64 MB)": bool(list(paths.models.glob("**/hi_IN-*.onnx"))),
        "local LLM (.gguf)": bool(list(paths.models.glob("**/*.gguf"))),
    }


def run_doctor(paths: Paths | None = None, config: AppConfig | None = None) -> DoctorReport:
    """Collect the full report. Never raises for environmental problems."""
    resolved = paths or get_paths()
    report = DoctorReport(
        python=platform.python_version(),
        platform=f"{platform.system()} {platform.release()}",
        architecture=platform.machine(),
        cpu_count=os.cpu_count() or 0,
        paths=resolved.as_dict(),
        config_path=str(resolved.config_file),
    )
    total, available = _memory_info()
    report.ram_total_gb, report.ram_available_gb = total, available

    db_version = 0
    config_ok = True
    try:
        loaded = config or AppConfig.load(resolved.config_file)
        loaded.validate()
    except ConfigError as exc:
        config_ok = False
        report.warnings.append(f"configuration problem: {exc}")
        loaded = AppConfig()
    report.config_ok = config_ok

    report.writable = _check_writable(resolved)
    if not report.writable:
        report.warnings.append(f"cannot write to {resolved.home} - settings will not persist")

    try:
        from shraddha.storage import db

        if resolved.db_file.exists():
            db_version = db.initialize(resolved.db_file)
    except Exception as exc:  # a corrupt DB must not hide the rest of the report
        report.warnings.append(f"database problem: {exc}")
    report.db_version = db_version

    report.extras = {name: _module_present(modules) for name, modules in OPTIONAL_EXTRAS.items()}
    report.models = _check_models(resolved)

    voices = tts.hindi_voices()
    report.voices = [str(voice) for voice in voices]
    report.engines = tts.available_engines(resolved.models, loaded.tts.piper_model)
    report.selected_engine = tts.select_engine(loaded.tts.engine, report.engines)

    mic_ok, mic_reason = audio_module.availability()
    report.microphone = {"available": mic_ok, "reason": mic_reason}
    report.asr_engines = engine_report(resolved.models)
    report.wake_mode = loaded.wake.mode

    _append_advice(report, loaded)
    return report


def _append_advice(report: DoctorReport, config: AppConfig) -> None:
    """Turn measurements into actionable warnings."""
    if not tts.is_windows():
        report.warnings.append(
            "not running on Windows: microphone, Windows voices and speech models are "
            "not exercised here (the core is portable for testing)"
        )
    if report.ram_total_gb is not None and report.ram_total_gb < RAM_FLOOR_GB:
        report.warnings.append(
            f"only {report.ram_total_gb:.1f} GB RAM; the supported floor is {RAM_FLOOR_GB} GB"
        )
    if config.llm.enabled and report.ram_total_gb is not None and report.ram_total_gb < RAM_LLM_GB:
        report.warnings.append(
            f"llm.enabled is true but {RAM_LLM_GB} GB RAM is recommended for a local LLM"
        )
    if report.selected_engine == tts.NONE and tts.is_windows():
        report.warnings.append(
            "no Hindi voice available: install the Hindi speech feature in Windows settings "
            "(Settings > Time & Language > Language > Hindi > Speech) or fetch a Piper voice"
        )
    if not report.extras.get("audio (sounddevice)"):
        report.warnings.append("microphone support not installed: pip install -e '.[audio]'")
    if not any(bool(info.get("ready")) for info in report.asr_engines.values()):
        report.warnings.append(
            "no Hindi speech model is ready: python scripts/fetch_models.py --set asr-light"
        )
    if not report.microphone.get("available"):
        report.warnings.append(f"microphone unavailable: {report.microphone.get('reason')}")
