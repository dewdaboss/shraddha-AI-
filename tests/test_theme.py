"""Tests for the design tokens - the design system is testable without Qt."""

from __future__ import annotations

import re

import pytest

from shraddha.ui.theme import (
    ANIM_HIDE_MS,
    ANIM_SHOW_MS,
    BUBBLE_MAX_WIDTH_RATIO,
    BUBBLE_ROLES,
    HINDI_FONT_STACK,
    OVERLAY_HEIGHT,
    OVERLAY_MIN_HEIGHT,
    OVERLAY_MIN_WIDTH,
    OVERLAY_WIDTH,
    PALETTE,
    bubble_style,
    css_font_family,
    stylesheet,
)

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
RGBA = re.compile(r"^rgba\(\s*\d+,\s*\d+,\s*\d+,\s*[\d.]+\)$")


@pytest.mark.parametrize(
    "value",
    [
        PALETTE.background,
        PALETTE.surface,
        PALETTE.surface_raised,
        PALETTE.border,
        PALETTE.neon,
        PALETTE.neon_dim,
        PALETTE.text,
        PALETTE.text_dim,
        PALETTE.text_faint,
        PALETTE.user_bubble,
        PALETTE.assistant_bubble,
        PALETTE.system_bubble,
        PALETTE.danger,
    ],
)
def test_palette_uses_valid_hex(value: str) -> None:
    assert HEX.match(value), f"{value} is not a #RRGGBB colour"


@pytest.mark.parametrize("value", [PALETTE.neon_glow, PALETTE.neon_faint])
def test_translucent_tokens_are_rgba(value: str) -> None:
    assert RGBA.match(value), f"{value} is not an rgba() colour"


def test_neon_is_the_only_accent() -> None:
    assert PALETTE.neon == "#00FF9C"
    assert PALETTE.background.startswith("#0"), "the background must stay near-black"


def test_hindi_font_comes_first() -> None:
    assert HINDI_FONT_STACK[0] == "Nirmala UI", "Nirmala UI ships with Windows 10"
    assert "Noto Sans Devanagari" in HINDI_FONT_STACK


def test_css_font_family_quotes_names() -> None:
    assert css_font_family(("A", "B")) == '"A", "B"'


def test_stylesheet_contains_the_visual_identity() -> None:
    qss = stylesheet()
    assert PALETTE.neon in qss
    assert PALETTE.background in qss
    assert "Nirmala UI" in qss
    assert qss.count("{") == qss.count("}"), "stylesheet braces must balance"


def test_stylesheet_covers_every_custom_widget() -> None:
    qss = stylesheet()
    for selector in ("QLineEdit#Input", "QScrollBar:vertical", "QMenu", "QPushButton#SendButton"):
        assert selector in qss, f"missing rule for {selector}"


@pytest.mark.parametrize("role", BUBBLE_ROLES)
def test_bubble_style_per_role(role: str) -> None:
    qss = bubble_style(role)
    assert "border-radius" in qss
    assert "QLabel" in qss


def test_user_bubble_is_tinted_and_distinct() -> None:
    assert bubble_style("user") != bubble_style("assistant")
    assert PALETTE.user_bubble in bubble_style("user")


def test_system_bubble_is_italic_and_borderless() -> None:
    qss = bubble_style("system")
    assert "italic" in qss
    assert "border: 1px solid transparent" in qss


def test_unknown_role_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown bubble role"):
        bubble_style("root")


def test_geometry_is_consistent() -> None:
    assert OVERLAY_WIDTH > OVERLAY_MIN_WIDTH
    assert OVERLAY_HEIGHT > OVERLAY_MIN_HEIGHT
    assert 0.5 <= BUBBLE_MAX_WIDTH_RATIO <= 0.9


def test_animations_are_short() -> None:
    assert 0 < ANIM_SHOW_MS <= 250, "slow entrances feel sluggish on a low-end laptop"
    assert 0 < ANIM_HIDE_MS <= 200
