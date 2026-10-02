"""Cross-platform clipboard write (used to hand KiCad a paste-ready block of symbols)."""
from __future__ import annotations

import os
import shutil
import subprocess


def set_clipboard(text: str) -> str:
    """Returns the method used, or raises RuntimeError."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            CF_UNICODETEXT = 13
            GMEM_MOVEABLE = 0x0002
            u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
            k32.GlobalAlloc.restype = wintypes.HGLOBAL
            k32.GlobalLock.restype = wintypes.LPVOID
            k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
            u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
            data = text.encode("utf-16-le") + b"\x00\x00"
            if not u32.OpenClipboard(None):
                raise RuntimeError("OpenClipboard failed")
            try:
                u32.EmptyClipboard()
                h = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
                p = k32.GlobalLock(h)
                ctypes.memmove(p, data, len(data))
                k32.GlobalUnlock(h)
                u32.SetClipboardData(CF_UNICODETEXT, h)
            finally:
                u32.CloseClipboard()
            return "win32"
        except Exception as e:  # noqa
            ps = shutil.which("powershell")
            if ps:
                subprocess.run([ps, "-NoProfile", "-Command", "$input | Set-Clipboard"], input=text, text=True, timeout=20)
                return "powershell"
            raise RuntimeError(f"Clipboard write failed: {e}")
    for cmd in (["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, input=text, text=True, timeout=20)
            return cmd[0]
    try:
        import tkinter

        r = tkinter.Tk()
        r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(text)
        r.update()
        r.destroy()
        return "tkinter"
    except Exception as e:  # noqa
        raise RuntimeError(f"No clipboard mechanism available: {e}")
