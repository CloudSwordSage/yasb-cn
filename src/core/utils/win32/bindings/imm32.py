"""Wrappers for imm32 win32 API functions to make them easier to use and have proper types"""

from ctypes import WinDLL
from ctypes.wintypes import HWND

imm32 = WinDLL("imm32", use_last_error=True)

imm32.ImmGetDefaultIMEWnd.argtypes = [HWND]
imm32.ImmGetDefaultIMEWnd.restype = HWND


def ImmGetDefaultIMEWnd(hwnd: int) -> int:
    """Return the default IME window for a window, or 0 when there is none."""
    return int(imm32.ImmGetDefaultIMEWnd(hwnd) or 0)
