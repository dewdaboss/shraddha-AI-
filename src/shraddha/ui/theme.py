"""Design tokens and stylesheet.

Deliberately **Qt-free**: this module only produces strings and numbers, so the design
system can be unit-tested on a machine with no display, no Qt libraries and no GPU.

Look: near-black surfaces, one neon-green accent, generous radii, no gradients that
cost a repaint.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Palette:
    """Single accent colour on near-black. Do not add a second accent."""

    background: str = "#050706"
    surface: str = "#0A0D0B"
    surface_raised: str = "#101512"
    border: str = "#1C2B23"

    neon: str = "#00FF9C"
    neon_dim: str = "#00C77A"
    neon_glow: str = "rgba(0, 255, 156, 0.16)"
    neon_faint: str = "rgba(0, 255, 156, 0.07)"

    text: str = "#E9F6F0"
    text_dim: str = "#84968C"
    text_faint: str = "#5A6B62"

    user_bubble: str = "#0E2A1E"
    assistant_bubble: str = "#111714"
    system_bubble: str = "#0C100E"

    danger: str = "#FF5470"


PALETTE = Palette()

#: Devanagari-capable fonts first, on Windows then elsewhere. Nirmala UI ships with
#: Windows 10 and is what the OS itself uses for Hindi - it gives correct conjuncts.
HINDI_FONT_STACK: tuple[str, ...] = (
    "Nirmala UI",
    "Noto Sans Devanagari",
    "Mangal",
    "Segoe UI",
    "DejaVu Sans",
)

UI_FONT_STACK: tuple[str, ...] = (
    "Segoe UI Variable Display",
    "Segoe UI",
    "Inter",
    "Noto Sans",
    "DejaVu Sans",
)

# Geometry
OVERLAY_WIDTH = 566
OVERLAY_HEIGHT = 486
OVERLAY_MIN_WIDTH = 420
OVERLAY_MIN_HEIGHT = 320
SCREEN_MARGIN = 48
RADIUS_CARD = 22
RADIUS_BUBBLE = 15
RADIUS_INPUT = 14
BUBBLE_MAX_WIDTH_RATIO = 0.80

# Motion (milliseconds). Short enough to feel instant, long enough to feel smooth.
ANIM_SHOW_MS = 170
ANIM_HIDE_MS = 130
ANIM_SLIDE_PX = 18
ANIM_PULSE_MS = 1500

#: Only these roles may appear in the chat; the QSS and the DB both rely on it.
BUBBLE_ROLES: tuple[str, ...] = ("user", "assistant", "system")


def css_font_family(stack: tuple[str, ...]) -> str:
    """Render a font stack as a CSS ``font-family`` value."""
    return ", ".join(f'"{name}"' for name in stack)


def bubble_style(role: str, palette: Palette = PALETTE) -> str:
    """Inline QSS for one chat bubble."""
    if role not in BUBBLE_ROLES:
        raise ValueError(f"unknown bubble role {role!r}; expected one of {BUBBLE_ROLES}")

    if role == "user":
        background, border, colour = palette.user_bubble, palette.neon_dim, palette.text
    elif role == "assistant":
        background, border, colour = palette.assistant_bubble, palette.border, palette.text
    else:
        background, border, colour = palette.system_bubble, "transparent", palette.text_dim

    italic = "font-style: italic;" if role == "system" else ""
    return (
        f"QFrame {{ background: {background};"
        f" border: 1px solid {border};"
        f" border-radius: {RADIUS_BUBBLE}px; {italic} }}"
        f" QLabel {{ color: {colour}; background: transparent; border: none; }}"
    )


def stylesheet(palette: Palette = PALETTE) -> str:
    """The application-wide stylesheet.

    Text anywhere in the UI uses the Hindi font stack, because a single missing glyph
    in a Hindi sentence is more damaging than an imperfect Latin typeface.
    """
    hindi = css_font_family(HINDI_FONT_STACK)
    ui = css_font_family(UI_FONT_STACK)
    return f"""
    QWidget {{
        color: {palette.text};
        font-family: {hindi};
        font-size: 14px;
    }}

    QWidget#Overlay {{
        background: transparent;
    }}

    QLabel#Title {{
        font-family: {ui};
        font-size: 15px;
        font-weight: 700;
        letter-spacing: 3px;
        color: {palette.neon};
    }}

    QLabel#Subtitle {{
        font-size: 11px;
        color: {palette.text_faint};
        letter-spacing: 0.5px;
    }}

    QLabel#Hint {{
        font-family: {ui};
        font-size: 11px;
        color: {palette.text_faint};
        background: {palette.neon_faint};
        border: 1px solid {palette.border};
        border-radius: 8px;
        padding: 3px 8px;
    }}

    QScrollArea#ChatScroll {{
        background: transparent;
        border: none;
    }}

    QWidget#ChatBody {{
        background: transparent;
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 6px;
        margin: 2px 0 2px 0;
    }}

    QScrollBar::handle:vertical {{
        background: {palette.border};
        border-radius: 3px;
        min-height: 28px;
    }}

    QScrollBar::handle:vertical:hover {{
        background: {palette.neon_dim};
    }}

    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}

    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}

    QLineEdit#Input {{
        background: {palette.surface_raised};
        border: 1px solid {palette.border};
        border-radius: {RADIUS_INPUT}px;
        padding: 10px 14px;
        font-size: 14px;
        color: {palette.text};
        selection-background-color: {palette.neon_dim};
        selection-color: {palette.background};
    }}

    QLineEdit#Input:focus {{
        border: 1px solid {palette.neon_dim};
    }}

    QLineEdit#Input::placeholder {{
        color: {palette.text_faint};
    }}

    QPushButton#IconButton {{
        background: transparent;
        border: none;
        border-radius: 9px;
        padding: 0px;
    }}

    QPushButton#IconButton:hover {{
        background: {palette.neon_faint};
    }}

    QPushButton#SendButton {{
        background: {palette.neon};
        border: none;
        border-radius: 12px;
    }}

    QPushButton#SendButton:hover {{
        background: #33FFB2;
    }}

    QPushButton#SendButton:pressed {{
        background: {palette.neon_dim};
    }}

    QPushButton#SendButton:disabled {{
        background: rgba(0, 255, 156, 0.12);
    }}

    QToolTip {{
        background: {palette.surface_raised};
        color: {palette.text};
        border: 1px solid {palette.border};
        padding: 4px 8px;
    }}

    QMenu {{
        background: {palette.surface};
        border: 1px solid {palette.border};
        border-radius: 10px;
        padding: 6px;
    }}

    QMenu::item {{
        padding: 7px 22px 7px 14px;
        border-radius: 7px;
        color: {palette.text};
    }}

    QMenu::item:selected {{
        background: {palette.neon_faint};
        color: {palette.neon};
    }}

    QMenu::separator {{
        height: 1px;
        background: {palette.border};
        margin: 5px 8px;
    }}
    """
