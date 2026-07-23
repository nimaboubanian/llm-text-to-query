"""Default CLI progress-narration callbacks shared by benchmark pipeline stages."""


def print_item_start(i: int, total: int, label: str) -> None:
    """Print the start of a per-item progress line, without a trailing newline."""
    print(f"  [{i}/{total}] {label}...", end="", flush=True)


def print_item_done(outcome: str) -> None:
    """Complete a per-item progress line started by print_item_start."""
    print(outcome)
