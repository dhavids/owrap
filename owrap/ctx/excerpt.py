"""
Transcript timestamp parsing and new-content excerpt extraction, for
both Claude Code (JSONL transcript) and Codex (JSONL rollout) sessions.
"""
import json
import re
import shlex
from datetime import datetime, timezone

from ..utils.parser.text import extract_useful_lines

MAX_RESULT_CHARS = 100


def ts_ns(stamp) -> int | None:
    """
    Parse a transcript entry's `timestamp` field (ISO-8601, `Z` suffix)
    into integer nanoseconds since epoch. None if missing or unparseable.
    """
    if not isinstance(stamp, str):
        return None
    try:
        value = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1_000_000_000)


def latest_event_ns(lines):
    latest = None
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = ts_ns(entry.get("timestamp"))
        if ts is not None:
            latest = max(latest or ts, ts)
    return latest


def lines_up_to_ceiling(lines: list, ceiling_ns: int) -> list:
    """
    Drop transcript lines timestamped after `ceiling_ns`; keeps lines
    with no parseable timestamp, since they can't be bounded.
    """
    kept = []
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            kept.append(line)
            continue
        ts = ts_ns(entry.get("timestamp"))
        if ts is not None and ts > ceiling_ns:
            continue
        kept.append(line)
    return kept


def fmt_ts_ns(ns: int) -> str:
    """
    Render a nanosecond timestamp as UTC ISO-8601, for log messages.
    """
    if not ns:
        return "(start)"
    return datetime.fromtimestamp(
        ns / 1_000_000_000, tz=timezone.utc,
    ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def last_attach_ts_ns(lines: list, owrap_sid: str) -> int:
    """
    Nanosecond timestamp of the most recent
    `__OWRAP_EXPORT__ SESSION_ID=<owrap_sid>` marker in the transcript
    — every owrap start/attach/refresh/sub/spawn prints this to its
    own stdout, which lands in the transcript as a tool_result.
    Returns 0 if the marker never appears (e.g. a session predating
    this convention, or a transcript that doesn't go back far enough).

    Timestamp-based rather than line-index-based: Claude Code's
    crash/resume flow can re-append an old transcript entry verbatim
    later in the file, at a higher line number but carrying its
    original (old) timestamp — a line-index floor would mistake that
    replay for a brand-new attach and skip everything in between.
    """
    marker = f"__OWRAP_EXPORT__ SESSION_ID={owrap_sid}"
    latest = 0
    for line in lines:
        if marker not in line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = ts_ns(entry.get("timestamp"))
        if ts is not None:
            latest = max(latest, ts)
    return latest


def is_context_update_request(text: str) -> bool:
    command = r"(?:--uall|--ctx|--updr|owrap\s+(?:ctx|updr))\b"
    return bool(
        re.search(rf"^\s*`?{command}", text, re.IGNORECASE)
        or re.search(
            rf"\b(?:run|do|try|execute|rerun|another)\b[^\n]{{0,80}}{command}",
            text, re.IGNORECASE,
        )
    )


def is_context_update_command(command: str) -> bool:
    return bool(re.search(
        r"(?:^|[/\s])owrap\s+(?:ctx|updr|ctx-hook|ctx-worker)\b",
        command,
    ))


def has_recognized_transcript_entries(
    lines: list, cursor_ns: int, source: str,
) -> bool:
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        entry_ts = ts_ns(entry.get("timestamp"))
        if entry_ts is None or entry_ts <= cursor_ns:
            continue
        payload = entry.get("payload", {})
        if source == "codex":
            if (entry.get("type") == "response_item"
                    and payload.get("type") == "message"):
                return True
            if (entry.get("type") == "event_msg"
                    and payload.get("type") in (
                        "user_message", "item_completed", "patch_apply_end",
                    )):
                return True
        elif entry.get("type") in ("assistant", "user"):
            return True
    return False


def extract_excerpt_lines(lines: list, cursor_ns: int) -> list:
    """
    Return excerpt lines from transcript JSONL lines timestamped after
    `cursor_ns`: assistant prose text, real Bash commands and
    Edit/Write/Read file paths from tool_use blocks (prefixed
    `$ `/`[Name] ` so the model can tell narration from a literal
    invocation), and the useful part of each tool_result for those
    tracked tools (see `extract_useful_lines`).
    """
    texts = []
    pending = {}
    skip_update_turn = False
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        entry_type = entry.get("type")
        content = entry.get("message", {}).get("content", [])
        if not isinstance(content, list):
            continue
        if entry_type == "user":
            prompt = " ".join(
                block.get("text", "") for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
            if prompt.strip():
                skip_update_turn = is_context_update_request(prompt)
        entry_ts = ts_ns(entry.get("timestamp"))
        if entry_ts is None or entry_ts <= cursor_ns:
            continue
        if entry_type == "assistant":
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    t = block.get("text", "")
                    if t.strip() and not skip_update_turn:
                        texts.append(t)
                elif btype == "tool_use":
                    name = block.get("name", "")
                    tool_input = block.get("input", {})
                    if name == "Bash":
                        cmd = tool_input.get("command", "")
                        if (cmd.strip() and not skip_update_turn
                                and not is_context_update_command(cmd)):
                            texts.append(f"$ {cmd}")
                            pending[block.get("id")] = name
                    elif name in ("Edit", "Write", "Read"):
                        path = tool_input.get("file_path", "")
                        if path and (not skip_update_turn or name != "Read"):
                            texts.append(f"[{name}] {path}")
                            pending[block.get("id")] = name
                    elif name == "NotebookEdit":
                        path = tool_input.get("notebook_path", "")
                        if path and not skip_update_turn:
                            texts.append(f"[{name}] {path}")
                            pending[block.get("id")] = name
        elif entry_type == "user":
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_result":
                    continue
                tool_use_id = block.get("tool_use_id")
                if tool_use_id not in pending:
                    continue
                del pending[tool_use_id]
                result = block.get("content", "")
                if isinstance(result, list):
                    result = " ".join(
                        b.get("text", "") for b in result
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                if not isinstance(result, str):
                    continue
                result = result.strip()
                if result:
                    useful = extract_useful_lines(result, MAX_RESULT_CHARS)
                    texts.append(f"-> {useful}")
    return texts


def extract_codex_excerpt_lines(lines: list, cursor_ns: int) -> list:
    """
    Extract assistant messages and file changes from Codex rollouts
    timestamped after `cursor_ns`.
    """
    texts = []
    skip_update_turn = False
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload = entry.get("payload", {})
        if entry.get("type") == "event_msg" and payload.get("type") == "user_message":
            message = payload.get("message", "")
            if isinstance(message, str):
                skip_update_turn = is_context_update_request(message)
        elif (
            entry.get("type") == "response_item"
            and payload.get("type") == "message"
        ):
            if payload.get("role") == "user":
                message = " ".join(
                    block.get("text", "") for block in payload.get("content", [])
                    if isinstance(block, dict)
                    and block.get("type") == "input_text"
                )
                if message.strip():
                    skip_update_turn = is_context_update_request(message)
        entry_ts = ts_ns(entry.get("timestamp"))
        if entry_ts is None or entry_ts <= cursor_ns:
            continue
        if entry.get("type") == "response_item":
            if payload.get("type") != "message" or payload.get("role") != "assistant":
                continue
            if skip_update_turn:
                continue
            for block in payload.get("content", []):
                if isinstance(block, dict) and block.get("type") == "output_text":
                    value = block.get("text", "")
                    if value.strip():
                        texts.append(value)
            continue
        if entry.get("type") != "event_msg":
            continue
        if payload.get("type") == "patch_apply_end" and payload.get("success"):
            for path in payload.get("changes", {}):
                texts.append(f"[FileChange] {path}")
            continue
        if payload.get("type") != "item_completed":
            continue
        item = payload.get("item", {})
        item_type = item.get("type")
        if item_type == "AgentMessage":
            if skip_update_turn:
                continue
            for block in item.get("content", []):
                if isinstance(block, dict) and block.get("type") == "text":
                    value = block.get("text", "")
                    if value.strip():
                        texts.append(value)
        elif item_type == "CommandExecution":
            command = item.get("command", [])
            include_command = (
                not skip_update_turn
                and not (isinstance(command, list) and command
                         and is_context_update_command(shlex.join(command)))
            )
            if include_command and isinstance(command, list) and command:
                texts.append(f"$ {shlex.join(command)}")
            if include_command:
                result = item.get("aggregated_output", "")
                if isinstance(result, str) and result.strip():
                    texts.append(
                        f"-> {extract_useful_lines(result, MAX_RESULT_CHARS)}"
                    )
        elif item_type == "FileChange":
            for path in item.get("changes", {}):
                texts.append(f"[FileChange] {path}")
    return texts
