"""Voice command understanding and safe execution.

Layout:

* :mod:`~shraddha.commands.router` - Hindi/Hinglish text -> :class:`Command` (pure);
* :mod:`~shraddha.commands.apps` - the allowlisted apps, folders and URLs;
* :mod:`~shraddha.commands.actions` - the only code that touches the operating system;
* :mod:`~shraddha.commands.confirmation` - the yes/no gate for sensitive commands.
"""

from __future__ import annotations

from shraddha.commands.actions import ActionExecutor, ActionResult
from shraddha.commands.apps import AppTarget, find_app, find_folder
from shraddha.commands.confirmation import ConfirmationGate, ConfirmationOutcome
from shraddha.commands.router import (
    INTENT_APP_OPEN,
    INTENT_FOLDER_OPEN,
    INTENT_INFO_DATE,
    INTENT_INFO_TIME,
    INTENT_POWER,
    INTENT_UNKNOWN,
    INTENT_VOICE_STOP,
    INTENT_VOICE_SWITCH,
    INTENT_WEB_OPEN,
    Command,
    CommandRouter,
)

__all__ = [
    "INTENT_APP_OPEN",
    "INTENT_FOLDER_OPEN",
    "INTENT_INFO_DATE",
    "INTENT_INFO_TIME",
    "INTENT_POWER",
    "INTENT_UNKNOWN",
    "INTENT_VOICE_STOP",
    "INTENT_VOICE_SWITCH",
    "INTENT_WEB_OPEN",
    "ActionExecutor",
    "ActionResult",
    "AppTarget",
    "Command",
    "CommandRouter",
    "ConfirmationGate",
    "ConfirmationOutcome",
    "find_app",
    "find_folder",
]
