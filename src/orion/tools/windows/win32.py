"""Read-only Win32 window enumeration (ctypes, no extra dependencies)."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
WM_CLOSE = 0x0010


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    pid: int
    title: str
    image: str      # process executable basename, lower-case ("" if not readable)


def _process_image(pid: int) -> str:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        k32.CloseHandle(h)


def visible_windows() -> list[WindowInfo]:
    """Visible, titled top-level windows."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    out: list[WindowInfo] = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        out.append(WindowInfo(int(hwnd), pid.value, buf.value, _process_image(pid.value)))
        return True

    user32.EnumWindows(proc(cb), 0)
    return out


def post_close(hwnd: int) -> bool:
    """Ask a window to close (WM_CLOSE), like clicking its X. The app may still prompt."""
    return bool(ctypes.WinDLL("user32").PostMessageW(wintypes.HWND(hwnd), WM_CLOSE, 0, 0))
