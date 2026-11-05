"""Tests for hotkey parsing - the part that must be correct before Windows sees it."""

from __future__ import annotations

import pytest

from shraddha.hotkey import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    MOD_WIN,
    HotkeyError,
    default_hotkey,
    format_hotkey,
    parse_hotkey,
)


def test_default_hotkey_parses() -> None:
    spec = parse_hotkey(default_hotkey())
    assert spec.modifiers == MOD_CONTROL | MOD_ALT
    assert spec.virtual_key == ord("S")
    assert spec.text == "Ctrl+Alt+S"


@pytest.mark.parametrize("text", ["ctrl+alt+s", "CTRL + ALT + S", " Ctrl+Alt+s ", "control+alt+s"])
def test_input_is_normalised(text: str) -> None:
    assert parse_hotkey(text).text == "Ctrl+Alt+S"


def test_all_modifiers_combine() -> None:
    spec = parse_hotkey("ctrl+alt+shift+win+k")
    assert spec.modifiers == MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_WIN
    assert spec.virtual_key == ord("K")


def test_function_and_named_keys() -> None:
    assert parse_hotkey("ctrl+f12").virtual_key == 0x7B
    assert parse_hotkey("alt+space").virtual_key == 0x20
    assert parse_hotkey("ctrl+shift+escape").virtual_key == 0x1B
    assert parse_hotkey("win+alt+6").virtual_key == ord("6")


def test_reserved_combination_is_rejected() -> None:
    with pytest.raises(HotkeyError, match="reserved"):
        parse_hotkey("ctrl+alt+delete")


def test_modifier_without_key_is_rejected() -> None:
    with pytest.raises(HotkeyError, match="no key"):
        parse_hotkey("ctrl+alt")


def test_key_without_modifier_is_rejected() -> None:
    with pytest.raises(HotkeyError, match="at least one modifier"):
        parse_hotkey("s")


@pytest.mark.parametrize("text", ["", "   ", None, 42])
def test_empty_input_is_rejected(text) -> None:
    with pytest.raises(HotkeyError):
        parse_hotkey(text)


def test_two_keys_are_rejected() -> None:
    with pytest.raises(HotkeyError, match="more than one key"):
        parse_hotkey("ctrl+a+b")


def test_empty_part_is_rejected() -> None:
    with pytest.raises(HotkeyError, match="empty part"):
        parse_hotkey("ctrl++s")


def test_unknown_key_is_rejected() -> None:
    with pytest.raises(HotkeyError, match="unsupported key"):
        parse_hotkey("ctrl+banana")


def test_register_modifiers_disable_auto_repeat() -> None:
    spec = parse_hotkey("ctrl+alt+s")
    assert spec.register_modifiers & MOD_NOREPEAT


def test_format_hotkey_round_trip() -> None:
    original = parse_hotkey("ctrl+shift+f5")
    assert format_hotkey(original.modifiers, original.virtual_key) == "Ctrl+Shift+F5"
