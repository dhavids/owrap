import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

from ..utils.paths import (
    context_path, _read_config, session_ctx_dir, session_ctx_transcript_path,
    get_model_chain, get_workspace_path, claude_transcript_path,
    context_lock_path, memory_lock_path, projects_lock_path,
    session_ctx_touched_path,
)
from ..utils.session.session_resolver import (
    _parse, session_file, owrap_sid_for_ccsid, all_attached_ccsid_pairs,
)
from ..utils.parser.sections import (
    extract_section, replace_section, split_top_sections, merge_log_entries,
)
from ..utils.parser.text import extract_useful_lines
from ..utils.dispatch.terminal import Terminal
from ..utils.filelock import file_lock
from ..constants import (
    CTX_SCOPED_TASK_TEMPLATE, CTX_CONTEXT_BLOCK, CTX_PROTOCOL_BLOCK,
    ANTI_SUMMARY_SUFFIX,
)

MAX_EXCERPT_CHARS = 4000
MAX_RESULT_CHARS = 100


class CtxWorkerRunner:
    """
    Context-manager dispatch: extracts new assistant transcript text for one
    attached window (ccsid) and dispatches an Update Context / Update
    Protocol task to the configured model.

    Three entry points share the same `_dispatch` core:
    - `run(input_path)` — background worker spawned by `CtxHookRunner` on
      Claude Code's PreCompact hook; always does both Context and Protocol.
    - `run_manual(mode, area)` — fire-and-forget dispatch for the planner's
      `--ctx`/`--updr` commands: validates fast, queues the requested half
      on a detached `ctx-worker` process, returns immediately.
    - `check_all_attached()` — background trigger check from the daemon's
      loop; dispatches both halves for every window with a non-empty diff.
    """

    def run(self, input_path: Path = None):
        """
        Execute a context-manager worker run from the given hook-payload
        path. `mode`/`area` in the payload are optional — absent (the real
        PreCompact hook payload) means both Context and Protocol, same as
        always; present (a manual `--ctx`/`--updr` handoff) restricts to
        the requested half.
        """
        if input_path is None:
            print("ctx-worker: --input required", file=sys.stderr)
            sys.exit(1)

        config = _read_config()
        if not config.get("owrap_context_manager_enabled", True):
            print("ctx-worker: context manager disabled, skipping")
            sys.exit(0)

        hook_data = json.loads(input_path.read_text())
        ccsid = hook_data.get("session_id", "")
        transcript_path = hook_data.get("transcript_path", "")
        mode = hook_data.get("mode")
        area = hook_data.get("area")

        owrap_sid = owrap_sid_for_ccsid(ccsid) if ccsid else None
        if not owrap_sid:
            print("ctx-worker: no matching owrap session", file=sys.stderr)
            sys.exit(0)

        self._dispatch_tracked(
            owrap_sid, ccsid, transcript_path, config,
            do_context=(mode != "updr"), do_protocol=(mode != "ctx"),
            area_override=area,
        )

    def run_manual(self, mode: str = None, area: str = None):
        """
        Fire-and-forget dispatch for the planner's `--ctx`/`--updr`/
        `--ctxupdr` commands: validates fast, queues the actual dispatch on
        a detached background process, and returns immediately — a model
        dispatch can take minutes, and the planner shouldn't block on it.
        Result shows up later as `ctx_status` in context.md, surfaced
        automatically in the orientation banner on the next `owrap
        refresh`/`owrap attach`.

        mode: "ctx" (Update Context only), "updr" (Update Protocol only),
        or None (both, in one dispatch — cheaper than calling `--ctx` then
        `--updr` separately, which would read the same unconsumed
        transcript excerpt twice and dispatch it twice).
        area: optional override for `--updr`/`--ctxupdr <area>`; defaults
        to the session's configured area.
        """
        config = _read_config()
        if not config.get("owrap_context_manager_enabled", True):
            print("context manager disabled (owrap_context_manager_enabled=false)")
            sys.exit(1)

        ccsid = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
        if not ccsid:
            print("No CLAUDE_CODE_SESSION_ID — run this from an attached window")
            sys.exit(1)

        owrap_sid = owrap_sid_for_ccsid(ccsid)
        if not owrap_sid:
            print("No owrap session attached to this window — run `owrap attach` first")
            sys.exit(1)

        transcript_path = str(claude_transcript_path(ccsid, get_workspace_path()))
        if not Path(transcript_path).exists():
            print(f"No transcript found at {transcript_path}")
            sys.exit(1)

        if mode != "ctx":
            sf_path = session_file(owrap_sid)
            d = _parse(sf_path) if sf_path.exists() else {}
            research = d.get("research", "")
            resolved_area = area or d.get("area", "")
            if not (research and resolved_area):
                print(
                    "updr: no research/area configured for this session — "
                    "pass an area explicitly or `owrap attach` a session with one"
                )
                sys.exit(1)

        ctx_dir = session_ctx_dir(owrap_sid, ccsid)
        ctx_dir.mkdir(parents=True, exist_ok=True)
        payload_path = ctx_dir / "manual.json"
        payload_path.write_text(json.dumps({
            "session_id": ccsid, "transcript_path": transcript_path,
            "mode": mode, "area": area,
        }))

        log_path = ctx_dir / "ctx.log"
        log_fd = open(str(log_path), "a")
        subprocess.Popen(
            ["owrap", "ctx-worker", "--input", str(payload_path)],
            stdout=log_fd, stderr=log_fd,
            start_new_session=True, close_fds=True,
        )
        log_fd.close()
        label = mode or "ctx+updr"
        print(
            f"{label} dispatch queued in background — check `owrap refresh` or "
            f"`owrap get context` for ctx_status once it finishes",
        )

    def check_all_attached(self):
        """
        Background trigger check (item 16): for every currently-attached
        window, dispatch an Update Context / Update Protocol pass if its
        transcript has grown since its last checkpoint. Cheap to call on a
        timer — `_dispatch` itself exits before touching the model when a
        window's excerpt since its checkpoint is empty, so a window with
        nothing new costs only a transcript line-count check.

        Called from the daemon loop; never raises — one window's failure
        is logged and skipped rather than blocking every other window.
        """
        config = _read_config()
        if not config.get("owrap_context_manager_enabled", True):
            return
        workspace = get_workspace_path()
        for ccsid, owrap_sid in all_attached_ccsid_pairs():
            try:
                transcript_path = claude_transcript_path(ccsid, workspace)
                if not transcript_path.exists():
                    continue
                self._dispatch_tracked(
                    owrap_sid, ccsid, str(transcript_path), config,
                    do_context=True, do_protocol=True,
                )
            except Exception as e:
                print(
                    f"ctx-worker: background check failed for ccsid={ccsid}: {e}",
                    file=sys.stderr,
                )

    def _dispatch_tracked(
        self, owrap_sid, ccsid, transcript_path, config,
        do_context, do_protocol, area_override=None,
    ) -> int:
        """
        Run `_dispatch` with ctx_status tracking in context.md: pending
        before, ok on clean success, failed on any error, including an
        uncaught exception — so a crash in our own code shows up too, not
        just a failed model dispatch.
        """
        real_context_path = context_path(owrap_sid)
        self._set_ctx_status(owrap_sid, real_context_path, "pending")
        try:
            rc = self._dispatch(
                owrap_sid, ccsid, transcript_path, config,
                do_context=do_context, do_protocol=do_protocol,
                area_override=area_override,
            )
        except Exception:
            self._set_ctx_status(owrap_sid, real_context_path, "failed")
            raise
        self._set_ctx_status(owrap_sid, real_context_path, "ok" if rc == 0 else "failed")
        return rc

    def _set_ctx_status(self, owrap_sid: str, real_context_path: Path, status: str):
        """
        Set `ctx_status` in context.md's Session block, inserting the
        field if it isn't there yet. No-op if context.md doesn't exist.
        """
        if not real_context_path.exists():
            return
        with file_lock(context_lock_path(owrap_sid)):
            lines = real_context_path.read_text().splitlines()
            start = None
            for i, line in enumerate(lines):
                if line.rstrip() == "## Session":
                    start = i
                    break
            if start is None:
                return
            end = len(lines)
            for i in range(start + 1, len(lines)):
                if lines[i].startswith("## "):
                    end = i
                    break
            for i in range(start, end):
                if lines[i].startswith("ctx_status:"):
                    lines[i] = f"ctx_status: {status}"
                    break
            else:
                lines.insert(start + 1, f"ctx_status: {status}")
            real_context_path.write_text("\n".join(lines) + "\n")

    def _dispatch(
        self, owrap_sid, ccsid, transcript_path, config,
        do_context, do_protocol, area_override=None,
    ) -> int:
        """
        Build the scoped sandbox, dispatch to the model, and apply its
        output back to the real context/memory/project files.

        Returns the opencode process's exit code (0 if nothing needed
        summarizing).
        """
        research = ""
        area = ""
        sf_path = session_file(owrap_sid)
        if sf_path.exists():
            d = _parse(sf_path)
            research = d.get("research", "")
            area = d.get("area", "")
        if area_override:
            area = area_override

        do_protocol = bool(do_protocol and research and area)

        counters = self._read_counters(owrap_sid, ccsid)
        transcript_offset = counters.get("transcript_offset", 0)

        if not transcript_path or not Path(transcript_path).exists():
            print("ctx-worker: transcript path missing", file=sys.stderr)
            return 1

        transcript_lines = Path(transcript_path).read_text().splitlines()
        total_lines = len(transcript_lines)

        # Floor at this window's last attach — a window can switch sessions.
        attach_floor = self._last_attach_line(transcript_lines, owrap_sid)
        effective_offset = max(transcript_offset, attach_floor)

        new_assistant_texts = self._extract_excerpt_lines(
            transcript_lines, effective_offset,
        )
        touched_entries = self._load_touched_entries(owrap_sid, ccsid)
        touched_lines = [
            f"[Touched] {e['path']}" + (f" — {e['note']}" if e.get("note") else "")
            for e in touched_entries
        ]
        combined_texts = new_assistant_texts + touched_lines

        if not combined_texts:
            print("ctx-worker: nothing to summarize", flush=True)
            counters["transcript_offset"] = total_lines
            self._write_counters(owrap_sid, counters, ccsid)
            return 0

        excerpt = "\n\n".join(combined_texts)
        if len(excerpt) > MAX_EXCERPT_CHARS:
            excerpt = excerpt[-MAX_EXCERPT_CHARS:]

        # Scoped sandbox — the model never sees a real path.
        ctx_dir = session_ctx_dir(owrap_sid, ccsid)
        ctx_dir.mkdir(parents=True, exist_ok=True)
        # A stray opencode.json here disqualifies OpenCode's free-tier models.
        (ctx_dir / "opencode.json").unlink(missing_ok=True)

        transcript_tmp = session_ctx_transcript_path(owrap_sid, ccsid)
        transcript_tmp.write_text(excerpt)

        real_context_path = context_path(owrap_sid)
        research_root = config.get("research_root", "")
        memory_path = projects_path = None
        if do_protocol and research_root:
            memory_path = Path(research_root) / "memory" / f"{research}.md"
            projects_path = Path(research_root) / "projects" / f"{research}.md"
        else:
            do_protocol = False

        # Model gets transcript only; our code merges its report deterministically.
        blocks = ""
        if do_context:
            blocks += CTX_CONTEXT_BLOCK
        if do_protocol:
            blocks += CTX_PROTOCOL_BLOCK.format(area=area)
        task_content = CTX_SCOPED_TASK_TEMPLATE.format(blocks=blocks)

        (ctx_dir / "input.md").write_text(task_content)
        output_path = ctx_dir / "output.md"

        print(
            f"ctx-worker: transcript lines "
            f"{transcript_offset}..{total_lines}",
            flush=True,
        )

        # Primary model retries once, then each fallback rung tries once.
        chain = get_model_chain(config)
        # Empty chain (no config at all): one attempt, opencode's own default.
        attempts = [chain[0], chain[0]] + chain[1:] if chain else [None]
        rc = 1
        output_text = None
        for model in attempts:
            rc, candidate = self._run_dispatch_attempt(
                ctx_dir, output_path, model,
            )
            if rc == 0 and candidate and self._validate_output(
                candidate, do_context, do_protocol,
            ):
                output_text = candidate
                break
            print(
                f"ctx-worker: attempt with model={model} produced no valid "
                "output, trying next",
                file=sys.stderr,
            )

        if output_text is None:
            print(
                "ctx-worker: all model attempts failed validation — "
                "leaving excerpt queued for the next dispatch",
                file=sys.stderr,
            )
            return 1

        self._apply_output(
            output_text, real_context_path,
            memory_path, projects_path, area, owrap_sid, research,
        )
        counters["transcript_offset"] = total_lines
        self._write_counters(owrap_sid, counters, ccsid)
        if touched_entries:
            self._clear_touched_entries(owrap_sid, ccsid)
        return rc

    def _run_dispatch_attempt(
        self, ctx_dir: Path, output_path: Path, model: str,
    ) -> tuple:
        """
        Run one opencode dispatch attempt in `ctx_dir` with `model`.

        Returns (returncode, output_text_or_None).
        """
        output_path.unlink(missing_ok=True)

        # pty below lets OpenCode auto-resolve/reject permissions on its own.
        cmd = ["opencode", "run", "--dir", str(ctx_dir)]
        if model:
            cmd.extend(["-m", model])
        cmd.extend([
            "--",
            # Plain English — --executor/--taskf needs AGENTS.md, unstaged here.
            "Read input.md in this directory and follow its instructions "
            f"exactly. {ANTI_SUMMARY_SUFFIX}",
        ])

        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        print(
            f"ctx-worker: dispatching opencode model={model or '(opencode default)'} "
            f"(scoped dir, no pool) at {ts}",
            flush=True,
        )
        cmd_str = " ".join(shlex.quote(c) for c in cmd)
        terminal = Terminal(verbose=False)
        # use_pty=True: without a real pty, OpenCode's permission prompt hangs.
        result = terminal.run(
            cmd_str, capture_output=False, print_output=True,
            use_pty=True, cwd=str(ctx_dir), timeout=180,
        )
        rc = result.get("returncode", 1)
        print(f"ctx-worker: opencode rc={rc}", flush=True)

        if not output_path.exists():
            print("ctx-worker: no output.md produced", file=sys.stderr)
            return rc, None
        return rc, output_path.read_text()

    def _validate_output(
        self, output_text: str, do_context: bool, do_protocol: bool,
    ) -> bool:
        """
        Confirm the model's output.md is structurally usable: it parses
        into the requested top-level sections, and each section's always-
        required heading (Focus for Context, Status for Project) survived.
        """
        if not output_text.strip():
            return False
        sections = split_top_sections(output_text, ("Context", "Memory", "Project"))
        if do_context:
            if "## Focus" not in sections.get("Context", ""):
                return False
        if do_protocol:
            if "### Status" not in sections.get("Project", ""):
                return False
        return True

    def _apply_output(
        self, output_text, real_context_path, memory_path, projects_path, area,
        owrap_sid, research,
    ):
        """
        Splice the model's scoped output.md back into the real files.
        "Log" fields (Key Locations, Decisions, How To, Components) are
        merged deterministically here — deduped against existing entries
        and capped — never left to the model's judgment, since it never
        saw the existing content to judge against. "Snapshot" fields
        (Focus, Environment, Status) are a full replace, since they
        describe current state rather than an accumulating history.
        """
        sections = split_top_sections(output_text, ("Context", "Memory", "Project"))

        context_block = sections.get("Context", "")
        if context_block:
            self._merge_context(context_block, real_context_path, owrap_sid)

        memory_block = sections.get("Memory", "")
        if memory_block and memory_path is not None:
            self._merge_memory(memory_block, memory_path, area, research)

        project_block = sections.get("Project", "")
        if project_block and projects_path is not None:
            self._merge_project(project_block, projects_path, area, research)

    def _merge_context(self, context_block, real_context_path, owrap_sid):
        """
        Apply the model's Context block to the real context.md.
        """
        with file_lock(context_lock_path(owrap_sid)):
            real_text = (
                real_context_path.read_text() if real_context_path.exists() else ""
            )

            for heading in ("## Focus", "## Environment"):
                new_text = extract_section(context_block, heading)
                if new_text:
                    real_text = replace_section(real_text, heading, new_text)

            for heading, cap, keep_fn in (
                ("## Key Locations", 5, self._key_location_still_exists),
                ("## Decisions", 7, None),
                ("## How To", 3, None),
            ):
                new_lines = self._entry_lines(context_block, heading)
                if new_lines or keep_fn is not None:
                    real_text = merge_log_entries(
                        real_text, heading, new_lines, cap=cap,
                        prepend=False, key_fn=self._bullet_key, keep_fn=keep_fn,
                    )

            real_context_path.write_text(real_text)

    def _merge_memory(self, memory_block, memory_path, area, research):
        """
        Apply the model's Memory block to the real memory.md's `## area`
        section. Components are merged (deduped, uncapped); any other
        `### <Subsystem>` the model wrote is appended as a new block —
        not merged into an existing subsystem of the same name.
        """
        with file_lock(memory_lock_path(research)):
            real_text = memory_path.read_text() if memory_path.exists() else ""
            heading = f"## {area}"
            area_text = extract_section(real_text, heading) or heading

            new_lines = self._entry_lines(memory_block, "### Components")
            if new_lines:
                area_text = merge_log_entries(
                    area_text, "### Components", new_lines,
                    cap=None, prepend=False, key_fn=self._bullet_key,
                )

            for sub_heading in self._sub_headings(memory_block, {"### Components"}):
                sub_block = extract_section(memory_block, sub_heading)
                if sub_block:
                    area_text = area_text.rstrip("\n") + "\n\n" + sub_block + "\n"

            real_text = replace_section(real_text, heading, area_text)
            memory_path.parent.mkdir(parents=True, exist_ok=True)
            memory_path.write_text(real_text)

    def _merge_project(self, project_block, projects_path, area, research):
        """
        Apply the model's Project block to the real projects.md's `## area`
        section. Status is a full replace; Decisions are merged — the
        model writes undated bullets, dated and prepended here.
        """
        with file_lock(projects_lock_path(research)):
            real_text = projects_path.read_text() if projects_path.exists() else ""
            heading = f"## {area}"
            area_text = extract_section(real_text, heading) or heading

            status_new = extract_section(project_block, "### Status")
            if status_new:
                area_text = replace_section(area_text, "### Status", status_new)

            bullet_lines = self._entry_lines(project_block, "### Decisions")
            if bullet_lines:
                today = time.strftime("%Y-%m-%d")
                row_lines = [self._decision_row(l, today) for l in bullet_lines]
                area_text = merge_log_entries(
                    area_text, "### Decisions", row_lines,
                    cap=150, prepend=True, key_fn=self._decision_row_key,
                )

            real_text = replace_section(real_text, heading, area_text)
            projects_path.parent.mkdir(parents=True, exist_ok=True)
            projects_path.write_text(real_text)

    def _entry_lines(self, block, heading):
        """
        Return the non-empty entry lines under `heading` within `block`,
        excluding the heading line itself.
        """
        section = extract_section(block, heading)
        if not section:
            return []
        return [l for l in section.splitlines()[1:] if l.strip()]

    def _sub_headings(self, block, exclude):
        """
        Return the distinct `### ` heading lines in `block` not in `exclude`.
        """
        headings = []
        for line in block.splitlines():
            stripped = line.rstrip()
            if stripped.startswith("### ") and stripped not in exclude:
                if stripped not in headings:
                    headings.append(stripped)
        return headings

    def _bullet_key(self, line: str) -> str:
        """
        Dedup key for a `- X — Y` style bullet: the `X` part.
        """
        stripped = line.strip()
        if stripped.startswith("- "):
            stripped = stripped[2:]
        return stripped.split(" — ")[0].strip().strip("`")

    def _key_location_still_exists(self, line: str) -> bool:
        """
        False only when a Key Locations bullet's leading path looks like a
        real repo path and that path no longer exists on disk — a stale
        entry left behind after the code moved or was deleted. A token
        with no file extension doesn't look like a path and is left alone
        rather than guessed at.
        """
        stripped = line.strip()
        if stripped.startswith("- "):
            stripped = stripped[2:]
        path_str = stripped.split(" ", 1)[0].strip("`") if stripped else ""
        if not path_str or "." not in path_str:
            return True
        workspace = get_workspace_path()
        if not workspace:
            return True
        return (Path(workspace) / path_str).exists()

    def _decision_row(self, bullet_line: str, today: str) -> str:
        """
        Convert a model-written `- decision — why` bullet into a dated
        `| date | decision | why |` table row.
        """
        stripped = bullet_line.strip()
        if stripped.startswith("- "):
            stripped = stripped[2:]
        if " — " in stripped:
            decision, why = stripped.split(" — ", 1)
        else:
            decision, why = stripped, ""
        return f"| {today} | {decision.strip()} | {why.strip()} |"

    def _decision_row_key(self, line: str) -> str:
        """
        Dedup key for a `| date | decision | why |` table row: the
        decision field.
        """
        parts = [p.strip() for p in line.strip().strip("|").split("|")]
        return parts[1] if len(parts) > 1 else line.strip()

    def _last_attach_line(self, lines: list, owrap_sid: str) -> int:
        """
        Index of the line right after the most recent
        `__OWRAP_EXPORT__ SESSION_ID=<owrap_sid>` marker in the transcript
        — every owrap start/attach/refresh/update-area/spawn prints this to
        its own stdout, which lands in the transcript as a tool_result.
        Returns 0 if the marker never appears (e.g. a session predating
        this convention, or a transcript that doesn't go back far enough).
        """
        marker = f"__OWRAP_EXPORT__ SESSION_ID={owrap_sid}"
        last_idx = -1
        for i, line in enumerate(lines):
            if marker in line:
                last_idx = i
        return last_idx + 1 if last_idx >= 0 else 0

    def _extract_excerpt_lines(self, lines: list, offset: int) -> list:
        """
        Return excerpt lines from transcript JSONL lines after `offset`:
        assistant prose text, real Bash commands and Edit/Write/Read file
        paths from tool_use blocks (prefixed `$ `/`[Name] ` so the model can
        tell narration from a literal invocation), and the useful part of
        each tool_result for those tracked tools (see `extract_useful_lines`).
        """
        texts = []
        pending = {}
        for line in lines[offset:]:
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
            if entry_type == "assistant":
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type")
                    if btype == "text":
                        t = block.get("text", "")
                        if t.strip():
                            texts.append(t)
                    elif btype == "tool_use":
                        name = block.get("name", "")
                        tool_input = block.get("input", {})
                        if name == "Bash":
                            cmd = tool_input.get("command", "")
                            if cmd.strip():
                                texts.append(f"$ {cmd}")
                                pending[block.get("id")] = name
                        elif name in ("Edit", "Write", "Read"):
                            path = tool_input.get("file_path", "")
                            if path:
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

    def _read_counters(self, session_id: str, ccsid: str) -> dict:
        from ..utils.session.donow import _counters_path
        p = _counters_path(session_id, ccsid)
        if p.exists():
            try:
                with open(p) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _write_counters(self, session_id: str, data: dict, ccsid: str):
        from ..utils.session.donow import _counters_path
        p = _counters_path(session_id, ccsid)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            json.dump(data, f)

    def _load_touched_entries(self, session_id: str, ccsid: str) -> list:
        """
        Return this window's pending `owrap touched` entries (item 14),
        each `{"path": ..., "note": ...}`. Empty list if none are queued.
        """
        p = session_ctx_touched_path(session_id, ccsid)
        if not p.exists():
            return []
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return []

    def _clear_touched_entries(self, session_id: str, ccsid: str):
        """
        Clear this window's pending-touched-paths file after its entries
        have been successfully applied.
        """
        session_ctx_touched_path(session_id, ccsid).unlink(missing_ok=True)


class CtxHookRunner:
    """
    Receive Claude Code's PreCompact hook data and dispatch a background
    context-manager worker for the firing window (ccsid).
    """

    def run(self):
        """
        Read hook data from stdin and spawn a ctx-worker process.
        """
        try:
            hook_data = json.load(sys.stdin)
        except (json.JSONDecodeError, EOFError):
            print("{}")
            sys.exit(0)

        config = _read_config()
        if not config.get("owrap_context_manager_enabled", True):
            print("{}")
            sys.exit(0)

        ccsid = hook_data.get("session_id", "")
        transcript_path = hook_data.get("transcript_path", "")
        cwd = hook_data.get("cwd", "")

        _ = (transcript_path, cwd)

        owrap_sid = owrap_sid_for_ccsid(ccsid) if ccsid else None

        if not owrap_sid:
            print("{}")
            sys.exit(0)

        ctx_dir = session_ctx_dir(owrap_sid, ccsid)
        ctx_dir.mkdir(parents=True, exist_ok=True)
        input_path = ctx_dir / "hook.json"
        input_path.write_text(json.dumps(hook_data))

        log_path = ctx_dir / "ctx.log"
        log_fd = open(str(log_path), "a")
        subprocess.Popen(
            ["owrap", "ctx-worker", "--input", str(input_path)],
            stdout=log_fd,
            stderr=log_fd,
            start_new_session=True,
            close_fds=True,
        )
        log_fd.close()

        print("{}")
        sys.exit(0)
