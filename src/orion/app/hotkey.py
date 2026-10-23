"""Global hotkey via Win32 RegisterHotKey, bound to a window handle.

WM_HOTKEY arrives in that window's nativeEvent. Registration can fail (another
program owns the combination); callers must surface that to the user.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

WM_HOTKEY = 0x0312
HOTKEY_ID = 0x0A11

_MODS = {"alt": 0x0001, "ctrl": 0x0002, "control": 0x0002, "shift": 0x0004, "win": 0x0008}
MOD_NOREPEAT = 0x4000
_KEYS = {
    "end": 0x23, "home": 0x24, "insert": 0x2D, "delete": 0x2E, "pause": 0x13,
    "escape": 0x1B, "esc": 0x1B, "space": 0x20, "backspace": 0x08,
    **{f"f{i}": 0x6F + i for i in range(1, 25)},
}


def parse_hotkey(spec: str) -> tuple[int, int]:
    """'ctrl+alt+end' -> (modifiers, virtual key). Raises ValueError if invalid."""
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    if not parts:
        raise ValueError("empty hotkey")
    *mods, key = parts
    m = 0
    for mod in mods:
        if mod not in _MODS:
            raise ValueError(f"unknown modifier {mod!r}")
        m |= _MODS[mod]
    if key in _KEYS:
        vk = _KEYS[key]
    elif len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    else:
        raise ValueError(f"unknown key {key!r}")
    if m == 0:
        raise ValueError("a global kill hotkey needs at least one modifier")
    return m, vk


def register(hwnd: int, spec: str) -> tuple[bool, str]:
    """Register `spec` for `hwnd`. Returns (ok, message)."""
    if sys.platform != "win32":
        return False, "global hotkey is Windows-only"
    try:
        mods, vk = parse_hotkey(spec)
    except ValueError as e:
        return False, f"invalid hotkey {spec!r}: {e}"
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    if user32.RegisterHotKey(hwnd, HOTKEY_ID, mods | MOD_NOREPEAT, vk):
        return True, f"global kill hotkey {spec} registered"
    err = ctypes.get_last_error()
    return False, f"could not register {spec} (Win32 error {err}); another app may own it"


def unregister(hwnd: int) -> None:
    if sys.platform == "win32":
        ctypes.WinDLL("user32").UnregisterHotKey(wintypes.HWND(hwnd), HOTKEY_ID)


def is_kill_hotkey_message(message_ptr: int) -> bool:
    msg = wintypes.MSG.from_address(message_ptr)
    return msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID
