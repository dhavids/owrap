"""
Generic text-formatting helpers shared across commands.
"""

USEFUL_LINE_KEYWORDS = (
    "error", "exception", "traceback", "fail", "warn", "denied", "refused",
    "not found", "rc=", "exit code",
)


def preview(text: str, words: int = 5) -> str:
    """
    Shorten text to its first and last `words` words, joined with an
    ellipsis if it was actually cut. Returns text unchanged if it's
    already short enough.
    """
    parts = text.split()
    if len(parts) <= words * 2:
        return text
    return " ".join(parts[:words]) + " ... " + " ".join(parts[-words:])


def extract_useful_lines(text: str, max_chars: int = 100) -> str:
    """
    Pull the signal out of multi-line command output instead of blindly
    truncating it: always keep the last non-blank line (usually the
    actual verdict — a test summary, an rc=, a final error), plus any
    line matching `USEFUL_LINE_KEYWORDS`. Falls back to just the last
    line if nothing else matches. Trimmed to `max_chars` if still over —
    interior matches drop first, the first match and the last line stay.
    """
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return ""
    last_line = lines[-1].strip()
    keyword_lines = [
        l.strip() for l in lines[:-1]
        if any(k in l.lower() for k in USEFUL_LINE_KEYWORDS)
    ]

    selected = keyword_lines + [last_line]
    joined = " | ".join(selected)
    # Drop interior matches first, keeping the first match and the last line
    while len(joined) > max_chars and len(selected) > 2:
        selected.pop(1 if len(selected) > 1 else 0)
        joined = " | ".join(selected)

    if len(joined) > max_chars:
        joined = joined[: max_chars - 3] + "..."
    return joined
