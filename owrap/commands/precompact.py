import json
import os
import subprocess
import sys
import time
from pathlib import Path

from ..utils.paths import (
    RUNTIME_DIR, RUNTIME_HOME, TASKS_DIR, context_path, _read_config,
    session_precompact_dir, session_precompact_input_path,
)
from ..utils.session_resolver import _parse, session_file
from ..constants import PRE_COMPACT_CTX_TEMPLATE, PRE_COMPACT_UPDR_TEMPLATE

MAX_EXCERPT_CHARS = 4000


class PrecompactWorkerRunner:
    """
    Process precompact worker tasks by summarizing assistant transcript text.
    """

    def run(self, input_path: Path = None):
        """
        Execute a precompact worker run from the given input path.
        """
        if input_path is None:
            print("precompact-worker: --input required", file=sys.stderr)
            sys.exit(1)

        hook_data = json.loads(input_path.read_text())
        claude_session_id = hook_data.get("session_id", "")
        transcript_path = hook_data.get("transcript_path", "")

        owrap_sid = None
        if claude_session_id:
            from ..utils.session_resolver import SESSIONS_DIR
            if SESSIONS_DIR.exists():
                for sf in sorted(SESSIONS_DIR.glob("*.session")):
                    d = _parse(sf)
                    if d.get("claude_session_id") == claude_session_id:
                        owrap_sid = d.get("session_id") or sf.stem
                        break

        if not owrap_sid:
            print("precompact-worker: no matching owrap session", file=sys.stderr)
            sys.exit(0)

        research = ""
        area = ""
        sf_path = session_file(owrap_sid)
        if sf_path.exists():
            d = _parse(sf_path)
            research = d.get("research", "")
            area = d.get("area", "")

        config = _read_config()
        research_root = config.get("research_root", "")
        context_path_str = str(context_path(owrap_sid))
        if research_root:
            memory_path_str = f"{research_root}/memory/{research}.md"
            projects_path_str = f"{research_root}/projects/{research}.md"
        else:
            memory_path_str = ""
            projects_path_str = ""

        counters = self._read_counters(owrap_sid)
        transcript_offset = counters.get("transcript_offset", 0)

        do_context = True
        do_protocol = True

        if not transcript_path or not Path(transcript_path).exists():
            print("precompact-worker: transcript path missing", file=sys.stderr)
            sys.exit(0)

        transcript_lines = Path(transcript_path).read_text().splitlines()
        total_lines = len(transcript_lines)

        new_assistant_texts = self._extract_assistant_text(
            transcript_lines, transcript_offset,
        )

        if not new_assistant_texts:
            print("precompact-worker: nothing to summarize", flush=True)
            counters["transcript_offset"] = total_lines
            self._write_counters(owrap_sid, counters)
            sys.exit(0)

        excerpt = "\n\n".join(new_assistant_texts)
        if len(excerpt) > MAX_EXCERPT_CHARS:
            excerpt = excerpt[-MAX_EXCERPT_CHARS:]

        pcdir = session_precompact_dir(owrap_sid)
        pcdir.mkdir(parents=True, exist_ok=True)
        transcript_tmp = pcdir / "precompact_transcript.txt"
        transcript_tmp.write_text(excerpt)

        task_content = ""
        if do_context:
            task_content = PRE_COMPACT_CTX_TEMPLATE.format(
                session_id=owrap_sid,
                transcript_path=str(transcript_tmp),
                context_path=context_path_str,
            )

        if do_protocol and research and area:
            updr_block = PRE_COMPACT_UPDR_TEMPLATE.format(
                research=research,
                area=area,
                session_id=owrap_sid,
                transcript_path=str(transcript_tmp),
                context_path=context_path_str,
                memory_path=memory_path_str,
                projects_path=projects_path_str,
            )
            if task_content:
                task_content = task_content + "\n\n" + updr_block
            else:
                task_content = updr_block

        task_file = session_precompact_input_path(owrap_sid)
        task_file.parent.mkdir(parents=True, exist_ok=True)
        task_file.write_text(task_content)

        cmd = [os.path.expanduser("~/bin/orun"), "--input", str(task_file)]
        if config.get("fast_model"):
            cmd.extend(["--model", config["fast_model"]])
        env = {**os.environ, "SESSION_ID": owrap_sid}

        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        print(f"precompact-worker: dispatching orun at {ts}", flush=True)
        print(
            f"precompact-worker: transcript lines "
            f"{transcript_offset}..{total_lines}",
            flush=True,
        )
        result = subprocess.run(cmd, capture_output=False, env=env)
        print(f"precompact-worker: orun rc={result.returncode}", flush=True)

        counters["transcript_offset"] = total_lines
        self._write_counters(owrap_sid, counters)

    def _extract_assistant_text(self, lines: list, offset: int) -> list:
        texts = []
        for line in lines[offset:]:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") != "assistant":
                continue
            message = entry.get("message", {})
            content = message.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        t = block.get("text", "")
                        if t.strip():
                            texts.append(t)
        return texts

    def _read_counters(self, session_id: str) -> dict:
        from ..utils.donow import _counters_path
        p = _counters_path(session_id)
        if p.exists():
            try:
                with open(p) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _write_counters(self, session_id: str, data: dict):
        from ..utils.donow import _counters_path
        p = _counters_path(session_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            json.dump(data, f)



class PrecompactRunner:
    """
    Receive precompact hook data and dispatch a background worker.
    """

    def run(self):
        """
        Read hook data from stdin and spawn a precompact worker process.
        """
        try:
            hook_data = json.load(sys.stdin)
        except (json.JSONDecodeError, EOFError):
            print("{}")
            sys.exit(0)

        claude_session_id = hook_data.get("session_id", "")
        transcript_path = hook_data.get("transcript_path", "")
        cwd = hook_data.get("cwd", "")

        _ = (transcript_path, cwd)

        owrap_sid = None
        if claude_session_id:
            from ..utils.session_resolver import SESSIONS_DIR
            if SESSIONS_DIR.exists():
                for sf in sorted(SESSIONS_DIR.glob("*.session")):
                    d = _parse(sf)
                    if d.get("claude_session_id") == claude_session_id:
                        owrap_sid = d.get("session_id") or sf.stem
                        break

        if not owrap_sid:
            print("{}")
            sys.exit(0)

        pcdir = session_precompact_dir(owrap_sid)
        pcdir.mkdir(parents=True, exist_ok=True)
        input_path = pcdir / "precompact.json"
        input_path.write_text(json.dumps(hook_data))

        log_path = pcdir / "precompact.log"
        log_fd = open(str(log_path), "a")
        subprocess.Popen(
            ["owrap", "precompact-worker", "--input", str(input_path)],
            stdout=log_fd,
            stderr=log_fd,
            start_new_session=True,
            close_fds=True,
        )
        log_fd.close()

        print("{}")
        sys.exit(0)
