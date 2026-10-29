"""
Generic text-formatting helpers shared across commands.
"""
import time

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


def oneline(text, limit: int = 150) -> str:
    """
    Collapse `text` to a single line (whitespace/newlines squashed),
    truncated to `limit` chars with a trailing ellipsis if cut.
    """
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


def preview_lines(text: str, max_lines: int = 12) -> str:
    """
    Return a text's first `max_lines` lines, with a trailing marker if
    more remains.
    """
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[:max_lines]) + "\n..."


def age_str(mtime: float) -> str:
    """
    Format a Unix timestamp as a short age relative to now
    ("5s"/"3m"/"2h 15m").
    """
    age = time.time() - mtime
    if age < 60:
        return f"{int(age)}s"
    if age < 3600:
        return f"{int(age / 60)}m"
    return f"{int(age / 3600)}h {int((age % 3600) / 60)}m"


def extract_useful_lines(text: str, max_chars: int = 100) -> str:
    """
    Pull the signal out of multi-line command output: keep the last
    non-blank line, plus any line matching `USEFUL_LINE_KEYWORDS`. Falls
    back to just the last line if nothing else matches. Trimmed to
    `max_chars` if still over: interior matches drop first, the first
    match and the last line stay.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    last_line = lines[-1].strip()
    keyword_lines = [
        line.strip() for line in lines[:-1]
        if any(keyword in line.lower() for keyword in USEFUL_LINE_KEYWORDS)
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
