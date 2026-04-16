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
FG_FROST = "\033[38;5;109m"     # ≈ #8FBCBB — system response text

BOLD = "\033[1m"
RESET = f"\033[0m{BG_BASE}"     # Reset styling but keep base background
FULL_RESET = "\033[0m"          # True reset — only for screen cleanup

# Glyphs
PROMPT = "❯"
ERROR = "✗"
WARN = "⚠"

# Braille spinner frames
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

_ANSI_RE = re.compile(r'\033\[[0-9;]*m')

_SQL_KW_RE = re.compile(
    r'\b(SELECT|FROM|WHERE|JOIN|LEFT|RIGHT|INNER|OUTER|FULL|CROSS|ON|'
    r'AND|OR|NOT|IN|EXISTS|BETWEEN|LIKE|IS|NULL|'
    r'GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT|OFFSET|'
    r'AS|DISTINCT|COUNT|SUM|AVG|MAX|MIN|'
    r'CASE|WHEN|THEN|ELSE|END|'
    r'WITH|UNION|ALL|ASC|DESC|'
    r'INSERT|UPDATE|DELETE|INTO|VALUES|SET)\b',
    re.IGNORECASE,
)


def highlight_sql(sql: str) -> str:
    """Color SQL keywords in cyan, leave the rest as base text."""
    return _SQL_KW_RE.sub(lambda m: f"{FG_CYAN}{m.group()}{FG_TEXT}", sql)


def format_table(df, max_rows=100):
    """Format a DataFrame as an aligned, indented table with styled headers."""
    truncated = len(df) > max_rows
    show = df.head(max_rows) if truncated else df

    headers = [str(c) for c in show.columns]
    rows = [[str(v) if str(v) != "nan" else "" for v in vals] for vals in show.values]

    widths = []
    for i, h in enumerate(headers):
        col_max = max((len(r[i]) for r in rows), default=0)
        widths.append(max(len(h), col_max))

    lines = []
    hdr = "   ".join(f"{h:<{w}}" for h, w in zip(headers, widths))
    lines.append(f"    {FG_MUTED}{hdr}{RESET}")

    sep = "   ".join("─" * w for w in widths)
    lines.append(f"    {FG_MUTED}{sep}{RESET}")

    for row in rows:
        data = "   ".join(f"{v:<{w}}" for v, w in zip(row, widths))
        lines.append(f"    {FG_TEXT}{data}{RESET}")

    if truncated:
        remaining = len(df) - max_rows
        lines.append(f"    {FG_MUTED}… {remaining} more rows{RESET}")

    return "\n".join(lines)


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
