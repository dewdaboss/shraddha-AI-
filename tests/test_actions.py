"""The action layer: what actually reaches the operating system.

Everything here runs against fakes. Nothing is launched, no folder is opened, and no
power state is touched - but the *decisions* are the real ones: an allowlist, argv
lists, and a refusal for anything the router could not vouch for.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shraddha.commands import actions
from shraddha.commands.actions import REFUSED, ActionExecutor, ActionResult, describe_history
from shraddha.commands.router import (
    INTENT_APP_OPEN,
    INTENT_FOLDER_OPEN,
    INTENT_INFO_TIME,
    INTENT_POWER,
    INTENT_WEB_OPEN,
    Command,
)

ARENA_URL = "https://arena.ai"


class FakePopen:
    """Records how a process *would* have been started."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def __call__(self, argv, **kwargs) -> object:
        self.calls.append((list(argv), kwargs))
        return object()


@pytest.fixture()
def popen() -> FakePopen:
    return FakePopen()


@pytest.fixture()
def opened_urls() -> list[str]:
    return []


@pytest.fixture()
def opened_paths() -> list[str]:
    return []


@pytest.fixture()
def executor(popen, opened_urls, opened_paths) -> ActionExecutor:
    return ActionExecutor(
        popen=popen,
        url_opener=lambda url: opened_urls.append(url) or True,
        path_opener=opened_paths.append,
    )


# --------------------------------------------------------------------- apps
def test_an_allowlisted_app_is_launched_with_an_argv_list(
    executor: ActionExecutor, popen: FakePopen, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(actions, "find_executable", lambda target: r"C:\fake\chrome.exe")

    result = executor.execute(Command(INTENT_APP_OPEN, "Chrome खोल रही हूँ।", {"target": "chrome"}))

    assert result.ok is True
    assert result.detail == r"C:\fake\chrome.exe"
    assert len(popen.calls) == 1
    argv, kwargs = popen.calls[0]
    assert argv == [r"C:\fake\chrome.exe"]
    assert kwargs["shell"] is False, "a shell would let a transcript inject commands"


def test_an_app_that_is_not_installed_says_so(
    executor: ActionExecutor, popen: FakePopen, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(actions, "find_executable", lambda target: None)

    result = executor.execute(Command(INTENT_APP_OPEN, args={"target": "chrome"}))

    assert result.ok is False
    assert result.detail == "not_found"
    assert "नहीं मिला" in result.message
    assert popen.calls == []


def test_an_app_outside_the_catalogue_is_refused(
    executor: ActionExecutor, popen: FakePopen
) -> None:
    result = executor.execute(Command(INTENT_APP_OPEN, args={"target": "photoshop"}))

    assert result.ok is False
    assert result.message == REFUSED
    assert result.detail == "unknown_target"
    assert popen.calls == []


def test_a_spoken_path_is_never_treated_as_a_program(
    executor: ActionExecutor, popen: FakePopen
) -> None:
    result = executor.execute(
        Command(INTENT_APP_OPEN, args={"target": r"C:\Windows\System32\cmd.exe"})
    )
    assert result.ok is False
    assert popen.calls == []


def test_a_launch_failure_is_reported_not_raised(
    executor: ActionExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args, **kwargs):
        raise OSError("access denied")

    monkeypatch.setattr(actions, "find_executable", lambda target: r"C:\fake\app.exe")
    executor.popen = boom

    result = executor.execute(Command(INTENT_APP_OPEN, args={"target": "notepad"}))
    assert result.ok is False
    assert "नहीं" in result.message or "नहीं" in result.message


# ---------------------------------------------------------------------- web
def test_an_allowlisted_url_opens(executor: ActionExecutor, opened_urls: list[str]) -> None:
    result = executor.execute(Command(INTENT_WEB_OPEN, args={"target": "arena", "url": ARENA_URL}))
    assert result.ok is True
    assert opened_urls == [ARENA_URL]


def test_an_app_entry_for_a_website_uses_the_catalogue_url(
    executor: ActionExecutor, opened_urls: list[str], popen: FakePopen
) -> None:
    result = executor.execute(Command(INTENT_APP_OPEN, args={"target": "arena"}))
    assert result.ok is True
    assert opened_urls == [ARENA_URL]
    assert popen.calls == []


@pytest.mark.parametrize(
    "url",
    ["https://example.com", "javascript:alert(1)", "file:///etc/passwd", "", "HTTPS://ARENA.AI"],
)
def test_a_url_outside_the_allowlist_is_refused(
    executor: ActionExecutor, opened_urls: list[str], url: str
) -> None:
    result = executor.execute(Command(INTENT_WEB_OPEN, args={"target": "x", "url": url}))
    assert result.ok is False
    assert opened_urls == []


def test_a_broken_browser_hook_does_not_crash_the_assistant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(url: str) -> bool:
        raise RuntimeError("no display")

    executor = ActionExecutor(url_opener=boom)
    result = executor.execute(Command(INTENT_WEB_OPEN, args={"target": "a", "url": ARENA_URL}))
    assert result.ok is False
    assert "वेबसाइट" in result.message


# ------------------------------------------------------------------- folders
def test_a_known_folder_opens_at_its_real_path(
    executor: ActionExecutor,
    opened_paths: list[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(actions, "folder_path", lambda key: tmp_path)

    result = executor.execute(
        Command(INTENT_FOLDER_OPEN, args={"target": "downloads", "path": "/etc"})
    )

    assert result.ok is True
    assert opened_paths == [str(tmp_path)], "the path from the transcript is ignored"


def test_an_unknown_folder_key_is_refused(
    executor: ActionExecutor, opened_paths: list[str]
) -> None:
    result = executor.execute(Command(INTENT_FOLDER_OPEN, args={"target": "etc", "path": "/etc"}))
    assert result.ok is False
    assert opened_paths == []


def test_a_missing_folder_is_reported(
    executor: ActionExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(actions, "folder_path", lambda key: None)
    result = executor.execute(Command(INTENT_FOLDER_OPEN, args={"target": "downloads"}))
    assert result.ok is False
    assert "फोल्डर" in result.message


def test_the_unix_opener_is_used_off_windows(
    popen: FakePopen, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(actions.sys, "platform", "linux")
    monkeypatch.setattr(actions, "folder_path", lambda key: tmp_path)

    executor = ActionExecutor(popen=popen)
    result = executor.execute(Command(INTENT_FOLDER_OPEN, args={"target": "downloads"}))

    assert result.ok is True
    assert popen.calls[0][0] == ["xdg-open", str(tmp_path)]


# --------------------------------------------------------------------- power
def test_power_actions_are_blocked_even_when_enabled() -> None:
    executor = ActionExecutor(allow_power_actions=True)
    result = executor.execute(
        Command(INTENT_POWER, args={"action": "shutdown"}, spoken="क्या बंद करूँ?")
    )
    assert result.ok is False
    assert result.detail == "power_disabled"
    assert "शटडाउन" in result.message or "shutdown" in result.message


def test_power_actions_are_blocked_by_default_with_the_spoken_refusal() -> None:
    result = ActionExecutor().execute(
        Command(INTENT_POWER, args={"action": "restart"}, spoken="सुरक्षा के लिए बंद है।")
    )
    assert result.ok is False
    assert result.message == "सुरक्षा के लिए बंद है।"


# ------------------------------------------------------------------ dry run
def test_dry_run_records_but_does_not_execute(popen: FakePopen) -> None:
    executor = ActionExecutor(dry_run=True, popen=popen)
    result = executor.execute(Command(INTENT_APP_OPEN, args={"target": "chrome"}))

    assert result.ok is True
    assert result.detail == "dry_run"
    assert result.message.startswith("[dry-run]")
    assert popen.calls == []


# ------------------------------------------------------------------- no-ops
def test_informational_intents_are_no_ops(executor: ActionExecutor, popen: FakePopen) -> None:
    result = executor.execute(Command(INTENT_INFO_TIME, spoken="समय बता रही हूँ।"))
    assert result.ok is True
    assert result.detail == "no-op: not an OS action"
    assert popen.calls == []


def test_history_keeps_every_command_it_saw(executor: ActionExecutor, monkeypatch) -> None:
    monkeypatch.setattr(actions, "find_executable", lambda target: "app.exe")
    executor.execute(Command(INTENT_APP_OPEN, args={"target": "chrome"}))
    executor.execute(Command(INTENT_INFO_TIME))

    assert describe_history(executor.history) == ["app.open:chrome", "info.time:"]


def test_action_result_is_immutable() -> None:
    result = ActionResult(True, "ठीक है।")
    with pytest.raises(AttributeError):
        result.ok = False  # type: ignore[misc]
