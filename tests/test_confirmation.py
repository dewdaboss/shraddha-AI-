"""The confirmation gate: a yes, a no, or another question.

Sensitive actions must be approved by the user in words. Anything ambiguous has to come
back as ``unclear`` and leave the command pending - an assistant that treats a cough as
consent is not safe.
"""

from __future__ import annotations

import pytest

from shraddha.commands.confirmation import ConfirmationGate, ConfirmationOutcome
from shraddha.commands.router import INTENT_POWER, Command

POWER = Command(INTENT_POWER, "क्या बंद करूँ?", {"action": "shutdown"}, needs_confirmation=True)


@pytest.fixture()
def gate() -> ConfirmationGate:
    gate = ConfirmationGate()
    gate.request(POWER)
    return gate


def test_a_gate_without_a_request_is_not_waiting() -> None:
    gate = ConfirmationGate()
    assert gate.is_waiting is False
    assert gate.pending is None
    assert gate.resolve("हाँ") == (ConfirmationOutcome.NONE, None)


def test_requesting_keeps_the_command(gate: ConfirmationGate) -> None:
    assert gate.is_waiting is True
    assert gate.pending is POWER


@pytest.mark.parametrize("answer", ["हाँ", "हां", "जी हाँ", "yes", "haan", "ha", "ok", "ठीक है", "करो"])
def test_approvals(gate: ConfirmationGate, answer: str) -> None:
    outcome, command = gate.resolve(answer)
    assert outcome is ConfirmationOutcome.APPROVED
    assert command is POWER
    assert gate.is_waiting is False, "one approval only"


@pytest.mark.parametrize("answer", ["नहीं", "नही", "no", "nahi", "na", "रहने दो", "cancel", "मत करो"])
def test_refusals(gate: ConfirmationGate, answer: str) -> None:
    outcome, command = gate.resolve(answer)
    assert outcome is ConfirmationOutcome.DECLINED
    assert command is None
    assert gate.is_waiting is False


@pytest.mark.parametrize("answer", ["शायद", "क्या बात कर रहे हो", "आज मौसम अच्छा है", ""])
def test_ambiguity_keeps_the_question_open(gate: ConfirmationGate, answer: str) -> None:
    outcome, command = gate.resolve(answer)
    assert outcome is ConfirmationOutcome.UNCLEAR
    assert command is None
    assert gate.is_waiting is True, "never assume consent"


def test_a_no_is_not_swallowed_by_a_yes_word(gate: ConfirmationGate) -> None:
    outcome, _ = gate.resolve("हाँ नहीं")
    assert outcome is ConfirmationOutcome.DECLINED


def test_punctuation_and_case_are_ignored(gate: ConfirmationGate) -> None:
    assert gate.resolve(" हाँ। ")[0] is ConfirmationOutcome.APPROVED


def test_the_command_runs_only_once(gate: ConfirmationGate) -> None:
    assert gate.resolve("हाँ")[0] is ConfirmationOutcome.APPROVED
    assert gate.resolve("हाँ") == (ConfirmationOutcome.NONE, None)


def test_clearing_forgets_the_command(gate: ConfirmationGate) -> None:
    gate.clear()
    assert gate.is_waiting is False
    assert gate.resolve("हाँ")[0] is ConfirmationOutcome.NONE
