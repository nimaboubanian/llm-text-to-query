"""ANSI 256-color constants and formatting helpers for the REPL."""

import os
import re
import sys

# Nord-inspired 256-color palette
BG_BASE = "\033[48;5;235m"       # ≈ #2E3440 — full screen background
BG_PANEL = "\033[48;5;236m"      # ≈ #3B4252 — header panel background
FG_TEXT = "\033[38;5;188m"       # ≈ #D8DEE9
FG_CYAN = "\033[38;5;110m"      # ≈ #88C0D0
FG_MUTED = "\033[38;5;60m"      # ≈ #4C566A
FG_RED = "\033[38;5;131m"       # ≈ #BF616A
FG_YELLOW = "\033[38;5;173m"    # ≈ #D08770
FG_GREEN = "\033[38;5;108m"     # ≈ #A3BE8C

BOLD = "\033[1m"
DIM = "\033[2m"
RESET = f"\033[0m{BG_BASE}"     # Reset styling but keep base background
FULL_RESET = "\033[0m"          # True reset — only for screen cleanup

# Glyphs
PROMPT = "❯"
ERROR = "✗"
WARN = "⚠"

# Braille spinner frames
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

_ANSI_RE = re.compile(r'\033\[[0-9;]*m')


def _cols():
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


def _rows():
    try:
        return os.get_terminal_size().lines
    except OSError:
        return 24


def rule(width=30):
    return f"  {FG_MUTED}{'─' * width}{RESET}"


def header(label, detail=None):
    suffix = f"  {FG_MUTED}({detail}){RESET}" if detail else ""
    return f"  {BOLD}{label}{RESET}{suffix}\n{rule()}"


def panel(lines):
    """Render lines with panel background, directly to stdout."""
    cols = _cols()
    for line in lines:
        # RESET contains BG_BASE; swap for BG_PANEL to keep panel background
        line = line.replace(BG_BASE, BG_PANEL)
        visible_len = len(_ANSI_RE.sub('', line))
        padding = max(0, cols - visible_len)
        sys.stdout.write(f"{BG_PANEL}{line}{' ' * padding}\n")
    sys.stdout.write(BG_BASE)
    sys.stdout.flush()


def out(text=""):
    """Print text with full-width background padding on every line."""
    cols = _cols()
    for line in str(text).split("\n"):
        visible_len = len(_ANSI_RE.sub('', line))
        padding = max(0, cols - visible_len)
        sys.stdout.write(f"{BG_BASE}{line}{' ' * padding}\n")
    sys.stdout.flush()


def write_spinner(text):
    """Overwrite current line with spinner text (no newline)."""
    cols = _cols()
    visible_len = len(_ANSI_RE.sub('', text))
    padding = max(0, cols - visible_len)
    sys.stdout.write(f"\r{BG_BASE}{text}{' ' * padding}")
    sys.stdout.flush()


def clear_line():
    """Clear the current line."""
    sys.stdout.write("\r\033[2K")
    sys.stdout.flush()


# ── Screen management ─────────────────────────────────────────────────


def init_screen():
    """Clear screen and fill with background color (normal screen mode)."""
    sys.stdout.write(f"{BG_BASE}\033[2J\033[H")
    sys.stdout.flush()


def set_scroll_region(top_row):
    """Pin everything above top_row; content below scrolls naturally.

    The terminal's native scrollback (mouse wheel, Shift+PgUp) remains
    available for reviewing previous output.
    """
    sys.stdout.write(f"\033[{top_row};{_rows()}r")
    sys.stdout.write(f"\033[{top_row};1H")
    sys.stdout.flush()


def cleanup_screen():
    """Reset scroll region, move cursor to bottom, and restore colors."""
    sys.stdout.write("\033[r")                  # reset scroll region
    sys.stdout.write(f"\033[{_rows()};1H")      # cursor to bottom
    sys.stdout.write(FULL_RESET)                # restore terminal colors
    sys.stdout.write("\n")
    sys.stdout.flush()
