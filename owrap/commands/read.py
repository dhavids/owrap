import argparse
import shlex
import sys
from datetime import datetime
from pathlib import Path

from ..utils.terminal import Terminal
from ..manager import Manager
from ..base import BaseRunner
from ..utils.paths import TASKS_DIR, context_path, _read_config

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
    "default": ". Answer in {max_lines} lines or fewer. No preamble, direct answer only.",
    "terse": ". Max 5 bullet points, one line each. Most important facts only. No preamble, no headers.",
    "structured": ". Use ## headers: Purpose, Key Parts, Watch-outs. Bullets under each — no prose. 25 lines max.",
    "code": ". List: (1) purpose in one sentence, (2) key classes/functions each with one-line description, (3) important side-effects or config caveats. 20 lines max. No preamble.",
    "exec": ". Write exactly one paragraph (4–6 sentences). Plain prose. Cover: what it does, what it is for, what an engineer needs to know. No preamble.",
    "bullets": ". Output bullet points only — no headers, no prose. Cover what, why, how, gotchas. 10 bullets max.",
    "deep": (
        ". Read strategically: for .py — __init__ first, then method signatures, then main();"
        " for .yaml — env/model sections first, then flag disabled/null values;"
        " for .md — tables and numbers first, then hypothesis/discussion."
        " Flag: None/stub values, config mutations, disabled features with active sub-config, magic numbers."
        " Compare numeric values across sections for inconsistencies."
        " 30 lines max. No preamble."
    ),
}


def _scale_timeout(size: int, base: int = 55) -> int:
    if size <=  5_000: return base
    if size <= 15_000: return 90
    if size <= 40_000: return 120
    return 180


class ReadRunner(BaseRunner):
    TASKS_DIR = TASKS_DIR

    def _run_grep(self, pattern: str, file_path=None):
        import subprocess
        if isinstance(file_path, list):
            if self.logger:
                self.logger.info("grep pattern=%r target=%s session=%s", pattern, file_path, self.manager.session_id or "none")
            cmd = ["grep", "-n", pattern] + [str(Path(f)) for f in file_path]
        else:
            target = Path(file_path) if file_path else Path.cwd()
            if self.logger:
                self.logger.info("grep pattern=%r target=%s session=%s", pattern, target, self.manager.session_id or "none")
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

    def _write_read_log(self, file_path: str, tag: str = ""):
        import fcntl
        read_log = self.manager.read_log_path
        read_log.parent.mkdir(parents=True, exist_ok=True)
        tag_str = f" {tag}" if tag else ""
        entry = f"{datetime.now().strftime('%Y-%m-%d %H:%M')}{tag_str} — {file_path}\n"
        read_log.touch(exist_ok=True)
        with open(read_log, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            existing = f.read()
            f.seek(0)
            f.write(entry + existing)
            f.truncate()


    def list_styles(self):
        print("oread prompt styles:")
        print()
        for name, suffix in PROMPT_STYLES.items():
            preview = suffix.strip(". ").replace("{max_lines}", "100")
            print(f"  {name:<12}  {preview[:80]}")
        print()
        print("auto-detect by extension (override with -p <style>):")
        by_style = {}
        for ext, style in FILE_TYPE_DEFAULTS.items():
            by_style.setdefault(style, []).append(ext)
        for style, exts in sorted(by_style.items()):
            print(f"  {style:<12}  {', '.join(sorted(exts))}")
        print()
        print(f"  fallback (unknown extension): {_STYLE_FALLBACK}")

    def run(self, file_path, summarise=False, details=None, log_time=True, grep=None, read_id=None, timeout=None, verbose=False, prompt_style=None):
        if grep is not None:
            self._run_grep(grep, file_path)
            return
        if isinstance(file_path, list):
            file_path = file_path[0]
        if read_id:
            print(f"[r:{read_id}]", flush=True)
        if self.logger:
            self.logger.info("read file=%s session=%s", file_path, self.manager.session_id or "none")
            if details:
                self.logger.debug("read details=%r", details)
        if not summarise and details is None:
            import subprocess
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
                    self._write_read_log(file_path, tag=f"[r:{read_id}]" if read_id else "")
                    sys.exit(0)
                print(f"[oread] {char_count} chars (>{OREAD_MAX_CHARS}) — forwarding to opencode for summary", flush=True)
                summarise = True

        url = self.manager.ensure_running()

        if prompt_style is None and file_path:
            ext = Path(file_path).suffix.lower()
            prompt_style = FILE_TYPE_DEFAULTS.get(ext, _STYLE_FALLBACK)

        prompt = f"Read the file at {file_path}"
        _ctx_cfg = _read_config()
        cp = context_path(self.manager.session_id)
        if _ctx_cfg.get("context_enabled", True) and self.manager.session_id and cp.exists() and cp.stat().st_size > 0:
            prompt = f"First read {cp}, then: " + prompt
        if summarise:
            prompt += ", summarise the content"
        if details:
            prompt += f", focusing on: {details}"
        style_key = prompt_style if prompt_style in PROMPT_STYLES else "default"
        prompt += PROMPT_STYLES[style_key].format(max_lines=OREAD_SUMMARY_LINES)

        cmd = ["opencode", "run"]
        if self.allow_all:
            cmd.append("--dangerously-skip-permissions")
        if url:
            cmd.extend(["--attach", url])
            cmd.extend(["--", shlex.quote(prompt)])
        else:
            fallback_file = self.TASKS_DIR / "task0.md"
            fallback_file.write_text(f"## Do\n\n{prompt}\n")
            cmd = ["opencode", "run"]
            if self.allow_all:
                cmd.append("--dangerously-skip-permissions")
            cmd.extend(["--", "--task", shlex.quote(str(fallback_file))])

        DEFAULT_TIMEOUT = 55
        if timeout is None:
            try:
                timeout = _scale_timeout(Path(file_path).stat().st_size, DEFAULT_TIMEOUT)
            except Exception:
                timeout = DEFAULT_TIMEOUT
        TIMEOUT = timeout

        mode_label = "-s" if (summarise and details is None) else "-d"
        sentinel_id = read_id or f"r_{int(__import__('time').time())}"
        sentinel_title = f"{mode_label} {file_path}"[:60]
        if self.logger:
            snippet = f" detail={details[:60]!r}" if details else ""
            id_str = f" id={read_id}" if read_id else ""
            self.logger.info("read opencode file=%s mode=%s%s%s session=%s",
                             file_path, mode_label, snippet, id_str,
                             self.manager.session_id or "none")
            self.logger.debug("read cmd=%s", " ".join(cmd))

        sentinel = self._write_sentinel(sentinel_id, sentinel_title, kind="read")
        self._install_sigterm_handler()

        rc = 1
        timed_out = False
        try:
            self.manager.t_cmd_start()
            result = Terminal(verbose=False).run(" ".join(cmd), print_output=True, capture_output=True, timeout=TIMEOUT)
            self.manager.t_cmd_end()
            if result.get("timed_out"):
                timed_out = True
                partial = (result.get("stdout") or "").strip()
                chars = len(partial)
                print(flush=True)
                print(f"[oread] timed out after {TIMEOUT}s", flush=True)
                print(f"  partial output printed above ({chars} chars captured)", flush=True)
                print(f"  rerun with -t <seconds> to extend (default: {DEFAULT_TIMEOUT}s)", flush=True)
                print(f"  the file or query is too large for -d — try -s (summarise) instead", flush=True)
                rc = 2
            else:
                rc = result.get("returncode", 1)
        except Exception as exc:
            self.manager.t_cmd_end()
            if self.logger:
                self.logger.error("read opencode error: %s", exc)
        finally:
            self._complete_sentinel(sentinel, rc, timed_out=timed_out)
            if self.logger:
                snippet = f" detail={details[:60]!r}" if details else ""
                id_str = f" id={read_id}" if read_id else ""
                self.logger.info("read opencode done file=%s mode=%s%s%s rc=%d%s",
                                 file_path, mode_label, snippet, id_str, rc,
                                 " (timeout)" if timed_out else "")
            self._write_read_log(file_path, tag=f"[r:{read_id}]" if read_id else "")
            self.manager.log_time(log_time)
        sys.exit(rc)


