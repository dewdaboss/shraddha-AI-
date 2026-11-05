"""Global hotkey parsing (platform independent).

The numeric constants below are Win32 virtual-key codes and ``RegisterHotKey``
modifier flags. Keeping the *parsing* here - pure Python, no ctypes, no Qt - means the
hotkey string from ``config.json`` can be validated and unit-tested on any platform;
only the registration itself (:mod:`shraddha.ui.hotkey`) is Windows-specific.
"""

from __future__ import annotations

from dataclasses import dataclass

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

_MODIFIERS: dict[str, int] = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "option": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "meta": MOD_WIN,
    "super": MOD_WIN,
    "cmd": MOD_WIN,
}

_KEYS: dict[str, int] = {
    "space": 0x20,
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "esc": 0x1B,
    "escape": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E,
    "del": 0x2E,
    "insert": 0x2D,
    "ins": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pgup": 0x21,
    "pagedown": 0x22,
    "pgdn": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "`": 0xC0,
    "-": 0xBD,
    "=": 0xBB,
    "[": 0xDB,
    "]": 0xDD,
    "\\": 0xDC,
    ";": 0xBA,
    "'": 0xDE,
    ",": 0xBC,
    ".": 0xBE,
    "/": 0xBF,
}

#: Combinations Windows never delivers to ``RegisterHotKey``; better to say so than to
#: silently never fire.
_RESERVED: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"ctrl", "alt", "delete"}),
        frozenset({"ctrl", "alt", "del"}),
    }
)

_DEFAULT = "ctrl+alt+s"


class HotkeyError(ValueError):
    """Raised for a hotkey string that cannot be registered."""


@dataclass(frozen=True, slots=True)
class HotkeySpec:
    """A parsed hotkey: Win32 modifier mask + virtual-key code."""

    modifiers: int
    virtual_key: int
    text: str

    @property
    def register_modifiers(self) -> int:
        """Modifier mask including ``MOD_NOREPEAT`` so holding the key fires once."""
        return self.modifiers | MOD_NOREPEAT

    def __str__(self) -> str:
        return self.text


def parse_hotkey(text: str) -> HotkeySpec:
    """Parse ``"ctrl+alt+s"`` into a :class:`HotkeySpec`.

    At least one modifier is required: a bare key would be swallowed system-wide and
    break normal typing everywhere else.
    """
    if not isinstance(text, str) or not text.strip():
        raise HotkeyError("hotkey must be a non-empty string such as 'ctrl+alt+s'")

    raw_parts = [part.strip().lower() for part in text.split("+")]
    if any(part == "" for part in raw_parts):
        raise HotkeyError(f"empty part in hotkey {text!r}")

    if frozenset(raw_parts) in _RESERVED:
        raise HotkeyError(f"{text!r} is reserved by Windows and can never fire")

    key_parts = [part for part in raw_parts if part not in _MODIFIERS]
    modifier_parts = [part for part in raw_parts if part in _MODIFIERS]

    if not modifier_parts:
        raise HotkeyError(f"hotkey {text!r} needs at least one modifier (ctrl, alt, shift or win)")
    if not key_parts:
        raise HotkeyError(f"hotkey {text!r} has modifiers but no key")
    if len(key_parts) > 1:
        raise HotkeyError(f"hotkey {text!r} has more than one key: {key_parts}")

    key = key_parts[0]
    virtual_key = _key_code(key)
    modifiers = 0
    for part in dict.fromkeys(modifier_parts):  # de-duplicate, keep order
        modifiers |= _MODIFIERS[part]

    return HotkeySpec(
        modifiers=modifiers, virtual_key=virtual_key, text=format_hotkey(modifiers, virtual_key)
    )


def _key_code(key: str) -> int:
    if key in _KEYS:
        return _KEYS[key]
    if len(key) == 1 and key.isalpha() and key.isascii():
        return ord(key.upper())
    if len(key) == 1 and key.isdigit():
        return ord(key)
    if key.startswith("f") and key[1:].isdigit():
        number = int(key[1:])
        if 1 <= number <= 24:
            return 0x70 + number - 1
    raise HotkeyError(f"unsupported key {key!r} in hotkey")


def format_hotkey(modifiers: int, virtual_key: int) -> str:
    """Render a canonical, human-readable hotkey such as ``"Ctrl+Alt+S"``."""
    parts: list[str] = []
    if modifiers & MOD_CONTROL:
        parts.append("Ctrl")
    if modifiers & MOD_ALT:
        parts.append("Alt")
    if modifiers & MOD_SHIFT:
        parts.append("Shift")
    if modifiers & MOD_WIN:
        parts.append("Win")
    parts.append(_key_name(virtual_key))
    return "+".join(parts)


def _key_name(virtual_key: int) -> str:
    for name, code in _KEYS.items():
        if code == virtual_key:
            return name.upper() if len(name) == 1 else name.capitalize()
    if 0x70 <= virtual_key <= 0x87:
        return f"F{virtual_key - 0x70 + 1}"
    if 0x41 <= virtual_key <= 0x5A:
        return chr(virtual_key)
    if 0x30 <= virtual_key <= 0x39:
        return chr(virtual_key)
    return f"0x{virtual_key:02X}"


def default_hotkey() -> str:
    """The shipped default: easy to reach, unlikely to collide."""
    return _DEFAULT
