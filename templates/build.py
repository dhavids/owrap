#!/usr/bin/env python3
"""
Keep the Markdown templates honest against the real CLI grammar.

`verify()` extracts every backtick-wrapped `owrap ...` example across
`templates/**/*.md` and checks it actually resolves through the real
kind/action resolver -- catches a doc describing a command that quietly
stopped existing (renamed kind, renamed action, retired verb) instead of
letting it sit stale until someone trips over it by hand.

`generate()` rewrites the "GENERATED" blocks in `self/commands.md` --
the workflow-grouped tables and full per-kind reference built from
each kind's own `usage` dict, and the config table built from
`config.json`/code constants -- so none of them can fall out of sync
with what the CLI actually does.

Run directly (`python3 templates/build.py`) to regenerate, or via
`deploy.py --check` (verify-only, no write) before promoting dev to
live.
"""
import contextlib
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from owrap.actions import usage_prefix  # noqa: E402
from owrap.cli import _resolve_kind_first  # noqa: E402
from owrap.ctx.dispatch import (  # noqa: E402
    AUTO_CTX_BACKOFF_SCHEDULE_S, CTX_MIN_CHARS, CTX_MIN_INTERVAL_S,
)
from owrap.kind import KIND_ALIASES, KIND_REGISTRY  # noqa: E402
from owrap.kind.dispatch import Dispatch  # noqa: E402

TEMPLATES_DIR = Path(__file__).resolve().parent
COMMANDS_MD = TEMPLATES_DIR / "self" / "commands.md"
CONFIG_JSON = TEMPLATES_DIR / "config.json"

PREFIXES = ("owrap", "~/bin/owrap", "{{BIN_DIR}}/owrap")
# A span may wrap across one prose line break (plain `\n`), but never a
# blank line (`\n\n`) -- that would mean crossing into the next paragraph
# or a fenced code block instead of just a wrapped sentence.
COMMAND_RE = re.compile(
    r"`((?:" + "|".join(re.escape(p) for p in PREFIXES) + r")(?!\w)"
    r"(?:(?!\n\n)[^`])*)`"
)

GENERATED_START = "<!-- BEGIN GENERATED: full command reference (templates/build.py) -->"
GENERATED_END = "<!-- END GENERATED: full command reference -->"

WORKFLOW_START = "<!-- BEGIN GENERATED: workflow tables (templates/build.py) -->"
WORKFLOW_END = "<!-- END GENERATED: workflow tables -->"

CONFIG_START = "<!-- BEGIN GENERATED: config table (templates/build.py) -->"
CONFIG_END = "<!-- END GENERATED: config table -->"

# (key(s), type, description) for every documented config.json entry.
# A tuple of keys shares one row (e.g. the three kill timeouts); their
# defaults are pulled from config.json in the same order, joined by "/".
# `string`-typed keys keep a "—" default -- config.json's value there is
# an example, not a shipped default worth advertising.
CONFIG_ROWS = (
    (("owrap_runner_enabled",), "bool",
     "Runner on/off switch. When `false`, dispatch tooling (`owrap "
     "read`/`exec`/`agent`/`task`, or `owrap fallback start`) is "
     "disabled and planner works directly."),
    (("owrap_context_manager_enabled",), "bool",
     "Gates the context-manager pipeline (Update Context/Update "
     "Protocol dispatch, including PreCompact), independent of the "
     "runner switch above."),
    (("permit_bypass_all",), "bool",
     "When `true`, `owrap p` auto-approves every Bash/Write/Edit call "
     "with no rule matching. Explicit opt-in only -- never implied by "
     "the runner switch."),
    (("runner_allow_all",), "bool",
     "Always pass `--dangerously-skip-permissions` to opencode "
     "dispatches."),
    (("runner_use_oread",), "bool",
     "Require file reads through `owrap read` (enables Read in "
     "permission matcher)."),
    (("context_injection_enabled",), "bool",
     "Inject session context file into task/msg prompts."),
    (("default_research",), "string",
     "Default target for legacy positional `start`."),
    (("workspace",), "string", "Path to the project root."),
    (("docs_root",), "string",
     "Root for projects, repositories, and the user-owned "
     "`instruction.md`."),
    (("research_root",), "string", "Legacy alias read during migration."),
    (("use_multiple_servers",), "bool", "Enable server pool mode."),
    (("max_servers",), "int", "Maximum concurrent opencode servers."),
    (("min_servers",), "int",
     "Minimum live servers the daemon maintains."),
    (("max_requests_per_server",), "int",
     "Request quota per server before graceful eviction."),
    (("idle_shutdown_s",), "float", "Idle seconds before server shutdown."),
    (("daemon_interval_s",), "float",
     "Seconds between daemon pool-lifecycle checks."),
    (("ctx_check_interval_s",), "float", None),  # built from code constants below
    (("runner_model",), "string",
     "Model for regular runner dispatch (`owrap task start`/`owrap "
     "exec start`)."),
    (("context_manager_model",), "string",
     "Model for context-manager tasks (Update Context/Update Protocol "
     "dispatch)."),
    (("context_fallback_model",), "string",
     "Fallback model when `context_manager_model` isn't set."),
    (("daemon_default_model",), "string",
     "Reserved for the daemon; not currently consumed (the daemon is "
     "pure lifecycle management, no model calls)."),
    (("msg_kill_s", "task_kill_s", "exec_kill_s"), "int",
     "No output kill timeouts for msg, task, exec jobs."),
    (("stall_notify_s",), "int",
     "Seconds before notification for a stalled job."),
    (("watchdog_poll_s",), "int", "Watchdog polling interval."),
    (("expected_duration_*",), "int",
     "Expected duration thresholds for msg/read/task/exec."),
)

# Display order and heading for each `usage[action]["group"]` value.
GROUP_TITLES = {
    "session": "## Session commands",
    "record": "## Record and context commands",
    "dispatch": "## Dispatch commands",
    "server": "## Server management",
}


def _is_placeholder(token: str) -> bool:
    """
    A token is part of the fixed kind/action prefix until it looks
    like a placeholder, flag, or alternation -- `<id>`, `[name]`,
    `--flag`, `{{PLACEHOLDER}}`, `task|exec`.
    """
    return (
        token.startswith(("-", "<", "[", "{{", '"', "'"))
        or "|" in token
    )


def fixed_tokens(command: str) -> list:
    """
    Return the literal kind/action tokens of a doc command example,
    stopping at the first placeholder/flag -- e.g. `owrap task start
    --msg <text>` -> `["task", "start"]`.
    """
    tokens = command.split()
    if tokens and tokens[0] in PREFIXES:
        tokens = tokens[1:]
    fixed = []
    for token in tokens:
        if _is_placeholder(token):
            break
        fixed.append(token)
    return fixed


def verify_command(fixed: list) -> str | None:
    """
    Resolve a fixed token sequence the same way the real CLI does.
    Returns an error string, or None if it checks out.
    """
    if not fixed:
        return None
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            resolved = _resolve_kind_first(list(fixed))
    except SystemExit:
        return f"`{' '.join(fixed)}` is ambiguous -- needs an explicit kind prefix"
    if resolved is None:
        return f"`{' '.join(fixed)}` does not resolve to any kind/action"
    kind = KIND_ALIASES.get(resolved[0], resolved[0])
    cls = KIND_REGISTRY[kind]
    if len(resolved) < 2:
        return None
    action = resolved[1]
    instance = cls()
    if getattr(instance, action, None) is not None:
        return None
    if getattr(instance, f"_default_{action}", None) is not None:
        return None
    if issubclass(cls, Dispatch):
        return None
    return f"kind '{kind}' does not support action '{action}' (from `{' '.join(fixed)}`)"


def verify_file(path: Path) -> list:
    """
    Return a list of "line N: message" errors found in one file.
    Scans the whole file (not line by line) so a backtick span that
    wraps across one prose line break is still caught.
    """
    errors = []
    text = path.read_text()
    for match in COMMAND_RE.finditer(text):
        error = verify_command(fixed_tokens(match.group(1)))
        if error:
            lineno = text.count("\n", 0, match.start()) + 1
            errors.append(f"line {lineno}: {error}")
    return errors


def verify(paths: list = None) -> dict:
    """
    Verify every example across `paths` (default: every template
    Markdown file, plus the promoted README). Returns {path: [errors]}
    for files with failures.
    """
    paths = paths or sorted(TEMPLATES_DIR.rglob("*.md")) + [ROOT / "README.md"]
    failures = {}
    for path in paths:
        errors = verify_file(path)
        if errors:
            failures[path] = errors
    return failures


def _kind_reference(kind: str, cls: type) -> str:
    usage = getattr(cls, "usage", {})
    if not usage:
        return ""
    lines = [f"### `owrap {kind}`", "", "| Action | Usage | Example |", "|---|---|---|"]
    for action, spec in usage.items():
        example = spec.get("examples", [""])[0] if spec.get("examples") else ""
        shape = spec.get("usage", "")
        full = f"{usage_prefix(kind, action)} {example}".strip()
        lines.append(f"| `{action}` | `{shape}` | `{full}` |")
    return "\n".join(lines)


def generate_commands_reference() -> str:
    """
    Build the full per-kind command reference from `KIND_REGISTRY`.
    """
    sections = []
    for kind, cls in sorted(KIND_REGISTRY.items()):
        section = _kind_reference(kind, cls)
        if section:
            sections.append(section)
    body = "\n\n\n".join(sections)
    return f"{GENERATED_START}\n## Full Command Reference\n\n{body}\n{GENERATED_END}"


def _grouped_rows() -> dict:
    """
    Collect every usage entry that declares a `group`, keyed by group,
    in `KIND_REGISTRY` order (alphabetical by kind, then declaration
    order within the kind).
    """
    rows = {group: [] for group in GROUP_TITLES}
    for kind, cls in sorted(KIND_REGISTRY.items()):
        for action, spec in getattr(cls, "usage", {}).items():
            group, purpose = spec.get("group"), spec.get("purpose")
            if group in rows and purpose:
                rows[group].append((kind, action, purpose))
    return rows


def _merge_same_purpose(rows: list) -> list:
    """
    Combine consecutive same-kind rows that share the same `purpose` into
    one `action1 / action2` row (e.g. daemon start/stop/restart).
    """
    merged = []
    for kind, action, purpose in rows:
        if merged and merged[-1][0] == kind and merged[-1][2] == purpose:
            prev_kind, prev_action, prev_purpose = merged[-1]
            merged[-1] = (prev_kind, f"{prev_action} / {action}", prev_purpose)
        else:
            merged.append((kind, action, purpose))
    return merged


def generate_workflow_tables() -> str:
    """
    Build the workflow-grouped `Command | Effect` tables straight from
    the same per-kind `usage` dicts the full reference reads, so a
    command's grouping/one-line effect can't drift from its real
    syntax independently.
    """
    rows_by_group = _grouped_rows()
    sections = []
    for group, title in GROUP_TITLES.items():
        rows = _merge_same_purpose(rows_by_group[group])
        if not rows:
            continue
        lines = [title, "", "| Command | Effect |", "|---|---|"]
        for kind, action, purpose in rows:
            lines.append(f"| `{usage_prefix(kind, action)}` | {purpose} |")
        sections.append("\n".join(lines))
    body = "\n\n\n".join(sections)
    return f"{WORKFLOW_START}\n{body}\n{WORKFLOW_END}"


def _format_duration(seconds: int) -> str:
    """Render a seconds count as `Xm`/`Xh` for prose use."""
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    return f"{seconds // 60}m"


def _config_default(keys: tuple, config: dict) -> str:
    """
    Render a row's Default cell from `config.json`'s real values --
    `—` for a key that isn't in config.json, a wildcard key, or a
    string-typed key (those are example values, not shipped defaults).
    """
    if keys[0].endswith("*"):
        return "varies"
    cells = []
    for key in keys:
        if key not in config or isinstance(config[key], str):
            return "—"
        value = config[key]
        cells.append("true" if value is True else "false" if value is False else str(value))
    return "/".join(f"`{cell}`" for cell in cells)


def generate_config_table() -> str:
    """
    Build the config-key reference table straight from `config.json`'s
    real values and, for the one row whose prose cites the auto-ctx
    cooldown/backoff numbers, the live code constants that drive them.
    """
    config = json.loads(CONFIG_JSON.read_text())
    ctx_desc = (
        "Seconds between the daemon's background checks for an "
        "attached window's unprocessed transcript diff -- an "
        f"auto-dispatch still only fires once the excerpt clears "
        f"`CTX_MIN_CHARS` ({CTX_MIN_CHARS // 1000}k) and this window's "
        f"own {CTX_MIN_INTERVAL_S // 60}-min cooldown, and "
        "otherwise follows a "
        f"{'/'.join(_format_duration(s) for s in AUTO_CTX_BACKOFF_SCHEDULE_S)}"
        f" schedule that cycles back to "
        f"{_format_duration(AUTO_CTX_BACKOFF_SCHEDULE_S[0])} after "
        "repeated opencode-down failures."
    )
    lines = ["| Key | Type | Default | Description |", "|---|---|---|---|"]
    for keys, type_, description in CONFIG_ROWS:
        if description is None:
            description = ctx_desc
        key_cell = " / ".join(f"`{key}`" for key in keys)
        default = _config_default(keys, config)
        lines.append(f"| {key_cell} | {type_} | {default} | {description} |")
    body = "\n".join(lines)
    return f"{CONFIG_START}\n{body}\n{CONFIG_END}"


def _replace_block(text: str, start: str, end: str, block: str) -> str:
    """
    Replace the `start`..`end` marked block in `text` with `block`,
    appending it instead if the markers aren't present yet.
    """
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    if pattern.search(text):
        return pattern.sub(block, text)
    return text.rstrip("\n") + "\n\n\n" + block + "\n"


def generate() -> None:
    """
    Replace the GENERATED blocks in `self/commands.md`: workflow
    grouping and full command reference from `KIND_REGISTRY`'s `usage`
    dicts, and the config table from `config.json`/code constants.
    """
    text = COMMANDS_MD.read_text()
    text = _replace_block(
        text, WORKFLOW_START, WORKFLOW_END, generate_workflow_tables(),
    )
    text = _replace_block(
        text, GENERATED_START, GENERATED_END, generate_commands_reference(),
    )
    text = _replace_block(
        text, CONFIG_START, CONFIG_END, generate_config_table(),
    )
    COMMANDS_MD.write_text(text)


def main() -> int:
    """
    `--check` only verifies (no write) -- for `deploy.py`, which must
    not mutate an already-validated, clean dev checkout. Plain runs
    (`owrap sync`, a developer running it directly) regenerate first.
    """
    check_only = "--check" in sys.argv[1:]
    if not check_only:
        generate()
    failures = verify()
    if not failures:
        verb = "verified" if check_only else "regenerated"
        print(f"build: command reference {verb}, all doc examples resolve")
        return 0
    print("build: stale command examples found —")
    for path, errors in failures.items():
        print(f"\n{path.relative_to(ROOT)}:")
        for error in errors:
            print(f"  {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
