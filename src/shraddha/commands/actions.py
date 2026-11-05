"""The only module that touches the operating system on behalf of a voice command.

Threat model: the text came from a microphone and may be wrong, malformed or adversarial.
Therefore:

* every target is re-resolved from the allowlists, ignoring anything in ``args`` that
  could have been altered;
* ``subprocess`` is always called with an argv list and ``shell=False`` - no shell, no
  string interpolation, no ``&``/``|`` surprises;
* an unknown intent is a *no-op*, never a fallback to "just run it".
"""

from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from shraddha.commands.apps import (
    FOLDER_ALIASES,
    WEB_ALLOWLIST,
    find_app,
    find_executable,
    folder_path,
)
from shraddha.commands.router import (
    INTENT_APP_OPEN,
    INTENT_FOLDER_OPEN,
    INTENT_POWER,
    INTENT_WEB_OPEN,
    Command,
)
from shraddha.logging_setup import get_logger

log = get_logger("commands")

NOT_FOUND = "यह ऐप इस कंप्यूटर पर नहीं मिला।"
REFUSED = "सुरक्षा कारणों से यह कार्य नहीं किया जा सकता।"


@dataclass(frozen=True, slots=True)
class ActionResult:
    """What happened, in words the assistant can speak."""

    ok: bool
    message: str
    intent: str = ""
    detail: str = ""


@dataclass
class ActionExecutor:
    """Executes validated commands, or records them in dry-run mode."""

    dry_run: bool = False
    popen: Callable[..., object] = subprocess.Popen
    url_opener: Callable[[str], bool] = webbrowser.open
    path_opener: Callable[[str], None] | None = None
    allow_power_actions: bool = False
    history: list[Command] = field(default_factory=list)

    def execute(self, command: Command) -> ActionResult:
        self.history.append(command)
        handlers = {
            INTENT_APP_OPEN: self._open_app,
            INTENT_WEB_OPEN: self._open_web,
            INTENT_FOLDER_OPEN: self._open_folder,
            INTENT_POWER: self._power,
        }
        handler = handlers.get(command.intent)
        if handler is None:
            return ActionResult(True, command.spoken, command.intent, "no-op: not an OS action")
        if self.dry_run:
            return ActionResult(
                True,
                f"[dry-run] {command.intent} {command.args}",
                command.intent,
                "dry_run",
            )
        return handler(command)

    # ------------------------------------------------------------------- apps
    def _open_app(self, command: Command) -> ActionResult:
        target = find_app(command.target)
        if target is None:
            log.warning("refused app.open for unknown target %r", command.target)
            return ActionResult(False, REFUSED, command.intent, "unknown_target")
        if target.is_web:
            # The URL comes from the catalog, never from the transcript.
            return self._open_url(target.url or "", command)

        executable = find_executable(target)
        if not executable:
            return ActionResult(False, f"{target.label}: {NOT_FOUND}", command.intent, "not_found")
        try:
            self.popen([executable], shell=False, close_fds=True)
        except OSError as exc:
            log.warning("could not launch %s: %s", executable, exc)
            return ActionResult(False, f"{target.label} खोल नहीं सकी।", command.intent, str(exc))
        return ActionResult(True, command.spoken, command.intent, executable)

    # -------------------------------------------------------------------- web
    def _open_web(self, command: Command) -> ActionResult:
        return self._open_url(command.args.get("url", ""), command)

    def _open_url(self, url: str, command: Command) -> ActionResult:
        if url not in WEB_ALLOWLIST:
            log.warning("refused web.open for non-allowlisted url %r", url)
            return ActionResult(False, REFUSED, command.intent, "url_not_allowed")
        try:
            self.url_opener(url)
        except Exception as exc:  # webbrowser can raise on headless systems
            log.warning("could not open %s: %s", url, exc)
            return ActionResult(False, "वेबसाइट नहीं खुल सकी।", command.intent, str(exc))
        return ActionResult(True, command.spoken, command.intent, url)

    # ----------------------------------------------------------------- folder
    def _open_folder(self, command: Command) -> ActionResult:
        key = command.target
        if key not in FOLDER_ALIASES:
            log.warning("refused folder.open for unknown key %r", key)
            return ActionResult(False, REFUSED, command.intent, "unknown_folder")

        path = folder_path(key)  # re-resolved: never the path in args
        if path is None or not path.is_dir():
            return ActionResult(False, "यह फोल्डर नहीं मिला।", command.intent, "not_found")
        try:
            self._open_path(path)
        except OSError as exc:
            log.warning("could not open %s: %s", path, exc)
            return ActionResult(False, "फोल्डर नहीं खुल सका।", command.intent, str(exc))
        return ActionResult(True, command.spoken, command.intent, str(path))

    def _open_path(self, path: Path) -> None:
        if self.path_opener is not None:
            self.path_opener(str(path))
            return
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
            return
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        self.popen([opener, str(path)], shell=False, close_fds=True)

    # ------------------------------------------------------------------- power
    def _power(self, command: Command) -> ActionResult:
        # Deliberately not implemented: an assistant that can be talked into shutting a
        # machine down is a liability while recognition is still imperfect.
        message = (
            f"कंप्यूटर {command.args.get('action', 'शटडाउन')} करना अभी समर्थित नहीं है।"
            if self.allow_power_actions
            else command.spoken or REFUSED
        )
        log.info("power action blocked: %s", command.args.get("action"))
        return ActionResult(False, message, command.intent, "power_disabled")


def describe_history(history: list[Command]) -> list[str]:
    """Compact trace used by tests and debug logs."""
    return [f"{command.intent}:{command.args.get('target', '')}" for command in history]
