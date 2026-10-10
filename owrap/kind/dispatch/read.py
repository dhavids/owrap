import shlex
import subprocess
import sys
import time
from pathlib import Path

from . import Dispatch
from ...dispatch import work
from ...dispatch.manager import Manager
from ...utils.constants import ANTI_SUMMARY_SUFFIX
from ...utils.dispatch.pool import (
    _pool_active, pick_server, release_server, update_last_used,
)
from ...utils.dispatch.terminal import Terminal
from ...utils.paths import FALLBACK_TASK, _read_config, context_path

OREAD_MAX_CHARS = 8_000
OREAD_SUMMARY_LINES = 100

FILE_TYPE_DEFAULTS = {
    ".py": "code",   ".sh": "code",   ".js": "code",  ".ts": "code",
    ".cpp": "code",  ".c": "code",    ".go": "code",  ".rs": "code",
    ".yaml": "structured", ".yml": "structured", ".json": "structured",
    ".toml": "structured", ".ini": "structured", ".cfg": "structured",
    ".md": "terse",  ".txt": "terse", ".rst": "terse",
    ".csv": "bullets", ".log": "bullets", ".tsv": "bullets",
}
_STYLE_FALLBACK = "terse"

PROMPT_STYLES = {
    "default": (
        ". Answer in {max_lines} lines or fewer."
        " No preamble, direct answer only."
    ),
    "terse": (
        ". Max 5 bullet points, one line each."
        " Most important facts only. No preamble, no headers."
    ),
    "structured": (
        ". Use ## headers: Purpose, Key Parts, Watch-outs."
        " Bullets under each — no prose. 25 lines max."
    ),
    "code": (
        ". List: (1) purpose in one sentence,"
        " (2) key classes/functions each with one-line description,"
        " (3) important side-effects or config caveats."
        " 20 lines max. No preamble."
    ),
    "exec": (
        ". Write exactly one paragraph (4–6 sentences)."
        " Plain prose. Cover: what it does, what it is for,"
        " what an engineer needs to know. No preamble."
    ),
    "bullets": (
        ". Output bullet points only — no headers, no prose."
        " Cover what, why, how, gotchas. 10 bullets max."
    ),
    "deep": (
        ". Read strategically: for .py — __init__ first,"
        " then method signatures, then main();"
        " for .yaml — env/model sections first,"
        " then flag disabled/null values;"
        " for .md — tables and numbers first,"
        " then hypothesis/discussion."
        " Flag: None/stub values, config mutations,"
        " disabled features with active sub-config,"
        " magic numbers."
        " Compare numeric values across sections"
        " for inconsistencies."
        " 30 lines max. No preamble."
    ),
}


def _scale_timeout(size: int, base: int = 55) -> int:
    if size <= 5_000:
        return base
    if size <= 15_000:
        return 90
    if size <= 40_000:
        return 120
    return 180


class Read(Dispatch):
    """
    Reads a file with style-aware opencode prompting, or greps one --
    the `oread` command. Overrides `start` directly: its own args
    (file path, style, grep, etc.) don't fit `Start`'s generic
    no-payload shape, and its dispatch isn't the generic callback
    pattern either -- see `kind/dispatch/__init__.py`.
    """

    kind = "read"

    usage = {
        "start": {
            "usage": "<file> [--summarise] [--details <text>] "
                     "[--grep <pattern>] [--id <id>]",
            "args": [
                ("file", "path to read"),
                ("grep", "search instead of reading"),
                ("id", "this read's own id, for parallel tracking"),
            ],
            "examples": ["owrap/cli.py", "owrap/cli.py --grep KIND_REGISTRY"],
            "purpose": "Read a file or list a directory",
            "group": "dispatch",
        },
        "get": {
            "usage": "<task_id>",
            "args": [("task_id", "a read task's id (the id passed to start)")],
            "examples": ["r_1234"],
        },
    }


    # Public Methods

    def start(
        self, file_path, summarise: bool = False, details: str = None,
        log_time: bool = True, grep: str = None, id: str = None,
        timeout: float = None, verbose: bool = False, prompt_style: str = None,
    ) -> None:
        """
        Read (or grep) `file_path`, forwarding to opencode for a
        style-aware summary if it's too large to print directly.
        """
        if grep is not None:
            self._run_grep(grep, file_path)
            return
        if isinstance(file_path, list):
            file_path = file_path[0]
        manager = Manager()
        if id:
            print(f"[r:{id}]", flush=True)
        if not summarise and details is None:
            p = Path(file_path)
            if not p.exists():
                print(f"{file_path}: does not exist")
                sys.exit(1)
            elif p.is_dir():
                result = subprocess.run(["ls", str(p)])
                sys.exit(result.returncode)
            else:
                text = p.read_text()
                char_count = len(text)
                if verbose or char_count <= OREAD_MAX_CHARS:
                    print(text, end="")
                    work.prepend_log_entry(
                        manager.read_log_path, file_path,
                        tag=f"[r:{id}]" if id else "",
                    )
                    sys.exit(0)
                print(
                    f"[oread] {char_count} chars (>{OREAD_MAX_CHARS})"
                    f" — forwarding to opencode for summary",
                    flush=True,
                )
                summarise = True

        if _pool_active():
            url = pick_server("read")
        else:
            url = manager.ensure_running()

        if prompt_style is None and file_path:
            ext = Path(file_path).suffix.lower()
            prompt_style = FILE_TYPE_DEFAULTS.get(ext, _STYLE_FALLBACK)

        prompt = f"Read the file at {file_path}"
        ctx_cfg = _read_config()
        cp = context_path(manager.session_id)
        if work.should_inject_context(ctx_cfg, manager.session_id, cp):
            prompt = work.context_prefix(cp) + prompt
        if summarise:
            prompt += ", summarise the content"
        if details:
            prompt += f", focusing on: {details}"
        style_key = prompt_style if prompt_style in PROMPT_STYLES else "default"
        prompt += PROMPT_STYLES[style_key].format(max_lines=OREAD_SUMMARY_LINES)
        prompt += " " + ANTI_SUMMARY_SUFFIX

        allow_all = work.allow_all()
        cmd = ["opencode", "run"]
        if allow_all:
            cmd.append("--dangerously-skip-permissions")
        if ctx_cfg.get("fast_model"):
            cmd.extend(["-m", ctx_cfg["fast_model"]])
        if url:
            cmd.extend(["--attach", url])
            cmd.extend(["--", shlex.quote(prompt)])
        else:
            fallback_file = FALLBACK_TASK
            fallback_file.write_text(f"## Do\n\n{prompt}\n")
            cmd = ["opencode", "run"]
            if allow_all:
                cmd.append("--dangerously-skip-permissions")
            if ctx_cfg.get("fast_model"):
                cmd.extend(["-m", ctx_cfg["fast_model"]])
            cmd.extend(["--", "--task", shlex.quote(str(fallback_file))])

        default_timeout = 55
        if timeout is None:
            try:
                timeout = _scale_timeout(Path(file_path).stat().st_size, default_timeout)
            except Exception:
                timeout = default_timeout

        mode_label = "-s" if (summarise and details is None) else "-d"
        sentinel_id = id or f"r_{int(time.time())}"
        sentinel_title = f"{mode_label} {file_path}"[:60]

        sentinel = work.write_sentinel(
            manager.session_id, sentinel_id, sentinel_title,
            kind="read", call_type="read",
        )
        state = work.new_signal_state()
        work.install_sigterm_handler(state)

        rc = 1
        timed_out = False
        try:
            manager.t_cmd_start()
            result = Terminal(verbose=False).run(
                " ".join(cmd), print_output=True,
                capture_output=True, timeout=timeout,
            )
            manager.t_cmd_end()
            if result.get("timed_out"):
                timed_out = True
                partial = (result.get("stdout") or "").strip()
                chars = len(partial)
                print(flush=True)
                print(f"[oread] timed out after {timeout}s", flush=True)
                print(
                    "  partial output printed above"
                    f" ({chars} chars captured)",
                    flush=True,
                )
                print(
                    "  rerun with -t <seconds> to extend"
                    f" (default: {default_timeout}s)",
                    flush=True,
                )
                print(
                    "  the file or query is too large for -d"
                    " — try -s (summarise) instead",
                    flush=True,
                )
                rc = 2
            else:
                rc = result.get("returncode", 1)
        except Exception:
            manager.t_cmd_end()
        finally:
            work.complete_sentinel(
                sentinel, rc, timed_out=timed_out,
                externally_killed=state["externally_killed"],
            )
            work.prepend_log_entry(
                manager.read_log_path, file_path,
                tag=f"[r:{id}]" if id else "",
            )
            manager.log_time(log_time)
            if url:
                try:
                    update_last_used(url)
                except Exception:
                    pass
                try:
                    release_server(url)
                except Exception:
                    pass
        sys.exit(rc)


    # Private Methods

    def _run_grep(self, pattern: str, file_path=None) -> None:
        if isinstance(file_path, list):
            cmd = ["grep", "-n", pattern] + [str(Path(f)) for f in file_path]
        else:
            target = Path(file_path) if file_path else Path.cwd()
            if target.is_file():
                cmd = ["grep", "-n", pattern, str(target)]
            else:
                cmd = ["grep", "-rn", pattern, str(target)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.stdout:
            print(result.stdout, end="")
        if result.returncode == 1:
            print(f"(no matches for {pattern!r} in {file_path})")
        elif result.returncode not in (0, 1):
            print(result.stderr, end="", file=sys.stderr)
        sys.exit(0)
