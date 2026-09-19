"""Make the Windows console print the card names we actually have.

Pokémon names, é and the em-dashes in the reports come out as mojibake in a
Windows console left on its legacy code page, which is exactly where a
double-clicked executable lands.
"""

from __future__ import annotations

import sys

UTF8_CODE_PAGE = 65001


def use_utf8() -> None:
    """Switch stdout/stderr to UTF-8, quietly doing nothing where it already is."""
    if sys.platform == "win32":
        _set_windows_code_page()
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # a redirected or closed stream
            pass


def _set_windows_code_page() -> None:  # pragma: no cover - Windows only
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleOutputCP(UTF8_CODE_PAGE)
        kernel32.SetConsoleCP(UTF8_CODE_PAGE)
    except Exception:
        pass  # no console attached, or an OS that will not play along
