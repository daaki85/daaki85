"""Scrolling the map with the mouse (DSCLOG's SCROLLING), switched and fed by the Ledger.

DSCLOG does the dragging: holding the right mouse button and moving scrolls the map with the
pointer, and a right click is still the game's (walk, use, look). The mouse wheel the game never
hears of (DOSBox 0.74, GOG's, doesn't pass it on), so in Windows the Ledger watches for it
(WheelWatch: a low-level mouse hook) while DOSBox's window is the one in front, and DSCLOG scrolls
the map by what the Ledger adds up for it: up and down, sideways with Shift or a sideways wheel.
"""

import struct
import sys
import threading
from typing import Callable, Optional, Tuple

TSR_SCROLL_ON, TSR_PAN_X, TSR_PAN_Y = 228, 230, 232  # DSCLOG's header
WHEEL_NOTCH = 120  # Windows' wheel delta for one notch
NOTCH_PIXELS = 48  # how far one notch scrolls the map (the game keeps its view to steps of 8)


def notch_pan(delta: int, sideways: bool) -> Tuple[int, int]:
    """The pixels (x, y) a wheel turn of DELTA scrolls the map: turned away from you (up), the
    view goes up (or left)."""
    pixels = -round(delta * NOTCH_PIXELS / WHEEL_NOTCH)
    return (pixels, 0) if sideways else (0, pixels)


class Scrolling:
    def __init__(self):
        self._on: Optional[bool] = None
        self._lock = threading.Lock()
        self._pending = [0, 0]

    def forget(self) -> None:
        """A new DSCLOG (the game started again): the switch is written again."""
        self._on = None

    def add(self, dx: int, dy: int) -> None:
        """Pixels to scroll the map by (from any thread)."""
        with self._lock:
            self._pending[0] += dx
            self._pending[1] += dy

    def update(self, gd, tsr_hdr: int, on: bool) -> None:
        guest = gd.guest
        if on != self._on:
            guest.write(tsr_hdr + TSR_SCROLL_ON, struct.pack("<H", int(on)))
            self._on = on
        with self._lock:
            dx, dy = self._pending
            self._pending = [0, 0]
        if on and (dx or dy):
            x, y = struct.unpack("<HH", guest.read(tsr_hdr + TSR_PAN_X, 4))
            guest.write(tsr_hdr + TSR_PAN_X, struct.pack("<HH", (x + dx) & 0xFFFF, (y + dy) & 0xFFFF))


class WheelWatch:
    """The mouse wheel turned over DOSBox's window (Windows only): ON_PAN(dx, dy) for each notch,
    while PID() names the process whose window is in front."""

    def __init__(self, pid: Callable[[], Optional[int]], on_pan: Callable[[int, int], None]):
        self._pid, self._on_pan = pid, on_pan
        self._thread: Optional[threading.Thread] = None
        self._thread_id = 0

    def start(self) -> bool:
        if sys.platform != "win32" or self._thread is not None:
            return False
        self._thread = threading.Thread(target=self._run, name="wheel", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        if self._thread_id:
            import ctypes
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)  # WM_QUIT

    def _run(self) -> None:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        WH_MOUSE_LL, WM_MOUSEWHEEL, WM_MOUSEHWHEEL, VK_SHIFT = 14, 0x020A, 0x020E, 0x10

        class MSLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

        HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

        def in_front() -> bool:
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(owner))
            pid = self._pid()
            return pid is not None and owner.value == pid

        def hook(code, wparam, lparam):
            if code >= 0 and wparam in (WM_MOUSEWHEEL, WM_MOUSEHWHEEL):
                try:
                    if in_front():
                        info = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                        delta = ctypes.c_short(info.mouseData >> 16).value
                        if wparam == WM_MOUSEHWHEEL:
                            delta = -delta  # (tilted right: the view goes right)
                        sideways = wparam == WM_MOUSEHWHEEL or bool(user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
                        self._on_pan(*notch_pan(delta, sideways))
                except Exception:  # (never stop the mouse over it)
                    pass
            return user32.CallNextHookEx(None, code, wparam, lparam)

        proc = HOOKPROC(hook)  # (kept alive while the thread runs)
        handle = user32.SetWindowsHookExW(WH_MOUSE_LL, proc, kernel32.GetModuleHandleW(None), 0)
        if not handle:
            return
        self._thread_id = kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnhookWindowsHookEx(handle)
