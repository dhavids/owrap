import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from ..utils.paths import (
    context_path, _read_config, session_ctx_dir, session_ctx_transcript_path,
    get_model_chain, get_workspace_path, claude_transcript_path,
    codex_transcript_path,
    context_lock_path, session_ctx_touched_path,
    session_ctx_counters_path,
)
from ..utils.session.resolver import (
    _parse, session_file, owrap_sid_for_ccsid, all_attached_ccsid_pairs,
    owrap_sid_for_codex_session_id, all_attached_codex_session_id_pairs,
)
from ..utils.parser.sections import (
    extract_section, replace_section, split_top_sections, merge_log_entries,
)
from ..utils.parser.text import extract_useful_lines
from ..utils.dispatch.terminal import Terminal
from ..utils.filelock import file_lock
from ..utils.log import context_jobs
from ..utils.memory.records import (
    register_discovered_repositories, resolve_memory_target,
    touched_repository_paths,
)
from ..constants import (
    CTX_SCOPED_TASK_TEMPLATE, CTX_CONTEXT_BLOCK,
    CTX_PROJECT_BLOCK, CTX_REPOSITORY_BLOCK, ANTI_SUMMARY_SUFFIX,
)

MAX_EXCERPT_CHARS = 12000
MAX_CODEX_EXCERPT_CHARS = 12000
MAX_RESULT_CHARS = 100


def _ts_ns(stamp) -> int | None:
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


class CtxWorkerRunner:
    """
    Context-manager dispatch: extracts new assistant transcript text for one
    attached window (ccsid) and dispatches an Update Context / Update
    Protocol task to the configured model.

    Three entry points share the same `_dispatch` core:
    - `run(input_path)` — background worker spawned by `CtxHookRunner` on
      Claude Code's PreCompact hook; always does both Context and Protocol.
    - `run_manual(mode, subproject)` — fire-and-forget dispatch for the planner's
      `--ctx`/`--updr` commands: validates fast, queues the requested half
      on a detached `ctx-worker` process, returns immediately.
    - `check_all_attached()` — background trigger check from the daemon's
      loop; dispatches both halves for every window with a non-empty diff.
    """

    def run(self, input_path: Path = None):
        """
        Execute a context-manager worker run from the given hook-payload
        path. `mode`/target override in the payload are optional — absent (the real
        PreCompact hook payload) means both Context and Protocol, same as
        always; present (a manual `--ctx`/`--updr` handoff) restricts to
        the requested half.
        """
        if input_path is None:
            print("ctx-worker: --input required", file=sys.stderr)
            sys.exit(1)

        hook_data = json.loads(input_path.read_text())
        job_dir = Path(hook_data["job_dir"]) if hook_data.get("job_dir") else None
        config = _read_config()
        if not config.get("owrap_context_manager_enabled", True):
            print("ctx-worker: context manager disabled, skipping")
            if job_dir:
                context_jobs.finish(job_dir, 1)
            return 1

        ccsid = hook_data.get("session_id", "")
        source = hook_data.get("source", "claude")
        transcript_path = hook_data.get("transcript_path", "")
        mode = hook_data.get("mode")
        subproject = hook_data.get("subproject")

        if source == "codex":
            owrap_sid = owrap_sid_for_codex_session_id(ccsid)
        else:
            owrap_sid = owrap_sid_for_ccsid(ccsid)
        if not owrap_sid:
            print("ctx-worker: no matching owrap session", file=sys.stderr)
            if job_dir:
                context_jobs.finish(job_dir, 1)
            return 1

        if job_dir:
            context_jobs.update(
                job_dir, status="running", started=time.time(),
                pid=os.getpid(), stage="reading transcript",
            )
        rc = 1
        self._job_dir = job_dir
        try:
            ctx_dir = session_ctx_dir(owrap_sid, ccsid)
            if job_dir:
                context_jobs.update(job_dir, stage="waiting for window")
            with file_lock(ctx_dir / "dispatch.lock"):
                if job_dir:
                    context_jobs.update(job_dir, stage="reading transcript")
                rc = self._dispatch_tracked(
                    owrap_sid, ccsid, transcript_path, config,
                    do_context=(mode != "updr"), do_protocol=(mode != "ctx"),
                    subproject_override=subproject,
                    source=source,
                )
        except Exception:
            if job_dir:
                context_jobs.finish(job_dir, 1)
            raise
        finally:
            self._job_dir = None
        if job_dir:
            context_jobs.finish(job_dir, rc)
        return rc

    def run_manual(self, mode: str = None, subproject: str = None):
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
        subproject: optional override for a project session's subproject;
        defaults to the session's target.
        """
        config = _read_config()
        if not config.get("owrap_context_manager_enabled", True):
            print("context manager disabled (owrap_context_manager_enabled=false)")
            sys.exit(1)

        ccsid = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
        source = "claude"
        if not ccsid:
            ccsid = os.environ.get("CODEX_SESSION_ID", "").strip()
            source = "codex"
        if not ccsid:
            print("No Claude or Codex session ID — run this from an attached window")
            sys.exit(1)

        if source == "codex":
            owrap_sid = owrap_sid_for_codex_session_id(ccsid)
        else:
            owrap_sid = owrap_sid_for_ccsid(ccsid)
        if not owrap_sid:
            print("No owrap session attached to this window — run `owrap attach` first")
            sys.exit(1)

        transcript = (
            codex_transcript_path(ccsid) if source == "codex"
            else claude_transcript_path(ccsid, get_workspace_path())
        )
        if transcript is None or not transcript.exists():
            print(f"No transcript found for {source} session {ccsid}")
            sys.exit(1)
        transcript_path = str(transcript)

        kind = None
        if mode != "ctx":
            sf_path = session_file(owrap_sid)
            d = _parse(sf_path) if sf_path.exists() else {}
            kind = d.get("target_kind")
            if kind == "project":
                target_data = dict(d)
                if subproject is not None:
                    target_data["subproject_id"] = (
                        "" if subproject == "main" else subproject
                    )
                try:
                    resolve_memory_target(target_data)
                except (FileNotFoundError, ValueError) as exc:
                    print(f"updr: {exc}", file=sys.stderr)
                    sys.exit(1)
            elif kind == "repository":
                if subproject is not None:
                    print(
                        "updr: repository sessions have no subproject",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                try:
                    resolve_memory_target(d)
                except (FileNotFoundError, ValueError) as exc:
                    print(f"updr: {exc}", file=sys.stderr)
                    sys.exit(1)
            else:
                print(
                    "updr: no project or repository target configured for "
                    "this session"
                )
                sys.exit(1)

        ctx_dir = session_ctx_dir(owrap_sid, ccsid)
        ctx_dir.mkdir(parents=True, exist_ok=True)
        label = "uall" if mode is None else mode
        job_dir = context_jobs.create(owrap_sid, ccsid, label)
        payload_path = job_dir / "manual.json"
        payload_path.write_text(json.dumps({
            "session_id": ccsid, "transcript_path": transcript_path,
            "mode": mode,
            "subproject": subproject if kind == "project" else None,
            "source": source,
            "job_dir": str(job_dir),
        }))

        log_path = job_dir / "output.log"
        log_fd = open(str(log_path), "a")
        try:
            process = subprocess.Popen(
                [sys.executable, "-m", "owrap.runner", "ctx-worker",
                 "--input", str(payload_path)],
                stdout=log_fd, stderr=log_fd,
                start_new_session=True, close_fds=True,
                cwd=str(Path(__file__).resolve().parents[2]),
            )
        except Exception:
            context_jobs.finish(job_dir, 1)
            raise
        finally:
            log_fd.close()
        if isinstance(process.pid, int):
            context_jobs.update(job_dir, pid=process.pid)
        label = mode or "ctx+updr"
        print(
            f"{label} dispatch queued as job {job_dir.name} — check `owrap stat` "
            f"or follow {log_path}",
        )

    def check_all_attached(self):
        """
        Background trigger check (item 16): for every currently-attached
        Claude or Codex window, dispatch an Update Context / Update
        Protocol pass if its transcript has grown since its last
        checkpoint. Cheap to call on a timer — `_dispatch` itself exits
        before touching the model when a window's excerpt since its
        checkpoint is empty, so a window with nothing new costs only a
        transcript line-count check.

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
        for cid, owrap_sid in all_attached_codex_session_id_pairs():
            try:
                transcript_path = codex_transcript_path(cid)
                if transcript_path is None or not transcript_path.exists():
                    continue
                self._dispatch_tracked(
                    owrap_sid, cid, str(transcript_path), config,
                    do_context=True, do_protocol=True, source="codex",
                )
            except Exception as e:
                print(
                    f"ctx-worker: background check failed for codex sid={cid}: {e}",
                    file=sys.stderr,
                )

    def _dispatch_tracked(
        self, owrap_sid, ccsid, transcript_path, config,
        do_context, do_protocol,
        subproject_override=None, source="claude",
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
                subproject_override=subproject_override,
                source=source,
            )
        except Exception:
            self._set_ctx_status(owrap_sid, real_context_path, "failed")
            raise
        self._set_ctx_status(owrap_sid, real_context_path, "ok" if rc == 0 else "failed")
        return rc

    def _set_ctx_status(self, owrap_sid: str, real_context_path: Path, status: str):
        """
        Set `ctx_status` and bump `last_updated` in context.md's Session
        block, inserting either field if it isn't there yet. No-op if
        context.md doesn't exist.
        """
        if not real_context_path.exists():
            return
        now_full = datetime.now().strftime("%Y-%m-%d %H:%M")
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
            saw_status = saw_updated = False
            for i in range(start, end):
                if lines[i].startswith("ctx_status:"):
                    lines[i] = f"ctx_status: {status}"
                    saw_status = True
                elif lines[i].startswith("last_updated:"):
                    lines[i] = f"last_updated: {now_full}"
                    saw_updated = True
            if not saw_status:
                lines.insert(start + 1, f"ctx_status: {status}")
                end += 1
            if not saw_updated:
                lines.insert(start + 1, f"last_updated: {now_full}")
            real_context_path.write_text("\n".join(lines) + "\n")

    def _dispatch(
        self, owrap_sid, ccsid, transcript_path, config,
        do_context, do_protocol,
        subproject_override=None, source="claude",
    ) -> int:
        """
        Build the scoped sandbox, dispatch to the model, and apply its
        output back to the session context and explicit memory records.

        Returns the opencode process's exit code (0 if nothing needed
        summarizing).
        """
        session_data = {}
        sf_path = session_file(owrap_sid)
        if sf_path.exists():
            session_data = _parse(sf_path)
        if subproject_override is not None:
            if session_data.get("target_kind") == "project":
                session_data["subproject_id"] = (
                    "" if subproject_override == "main"
                    else subproject_override
                )

        target = (
            resolve_memory_target(session_data)
            if do_protocol and session_data.get("target_kind") else None
        )
        do_protocol = bool(do_protocol and target)

        counters = self._read_counters(owrap_sid, ccsid)
        cursor_ns = counters.get("transcript_cursor_ns", 0)

        if not transcript_path or not Path(transcript_path).exists():
            print("ctx-worker: transcript path missing", file=sys.stderr)
            return 1

        transcript_lines = Path(transcript_path).read_text().splitlines()

        # Floor at this window's last attach — a window can switch sessions.
        # Timestamp-based, not line-index-based: Claude Code's crash/resume
        # flow can re-append old transcript entries verbatim later in the
        # file, and a replayed entry keeps its original (old) timestamp, so
        # it can't masquerade as a newer attach the way a line number would.
        attach_ts_ns = self._last_attach_ts_ns(transcript_lines, owrap_sid)
        effective_cursor_ns = max(cursor_ns, attach_ts_ns)
        # Never move the cursor backward — an empty/malformed transcript
        # read shouldn't re-expose content already marked consumed.
        new_cursor_ns = max(
            self._latest_event_ns(transcript_lines) or 0, effective_cursor_ns,
        )
        event_ns = new_cursor_ns

        if source == "codex":
            new_assistant_texts = self._extract_codex_excerpt_lines(
                transcript_lines, effective_cursor_ns,
            )
        else:
            new_assistant_texts = self._extract_excerpt_lines(
                transcript_lines, effective_cursor_ns,
            )
        touched_entries = self._load_touched_entries(owrap_sid, ccsid)
        touched_lines = [
            f"[Touched] {e['path']}" + (f" — {e['note']}" if e.get("note") else "")
            for e in touched_entries
        ]
        repository_paths = {}
        if target:
            changed_paths = [entry["path"] for entry in touched_entries]
            for line in new_assistant_texts:
                match = re.match(r"\[(?:Edit|Write)\]\s+(\S+)", line)
                if match:
                    changed_paths.append(match.group(1))
            repository_paths = touched_repository_paths(
                target, changed_paths, session_data.get("workspace", ""),
            )
            repository_paths.update(register_discovered_repositories(
                target, changed_paths, session_data.get("workspace", ""),
            ))
        combined_texts = new_assistant_texts + touched_lines

        if not combined_texts:
            print("ctx-worker: nothing to summarize", flush=True)
            if self._has_recognized_transcript_entries(
                transcript_lines, effective_cursor_ns, source,
            ):
                counters["transcript_cursor_ns"] = new_cursor_ns
                self._write_counters(owrap_sid, counters, ccsid)
            return 0

        excerpt = "\n\n".join(combined_texts)
        excerpt_limit = (
            MAX_CODEX_EXCERPT_CHARS if source == "codex" else MAX_EXCERPT_CHARS
        )
        if len(excerpt) > excerpt_limit:
            dropped = len(excerpt) - excerpt_limit
            print(f"ctx-worker: excerpt truncated, dropped {dropped} chars")
            excerpt = excerpt[-excerpt_limit:]

        job_dir = getattr(self, "_job_dir", None)
        # Keep each model attempt isolated from other windows and jobs.
        ctx_dir = job_dir / "work" if job_dir else session_ctx_dir(owrap_sid, ccsid)
        ctx_dir.mkdir(parents=True, exist_ok=True)
        # A stray opencode.json here disqualifies OpenCode's free-tier models.
        (ctx_dir / "opencode.json").unlink(missing_ok=True)

        transcript_tmp = session_ctx_transcript_path(owrap_sid, ccsid)
        if job_dir:
            transcript_tmp = ctx_dir / "transcript.txt"
        transcript_tmp.write_text(excerpt)
        if job_dir:
            (job_dir / "transcript.txt").write_text(excerpt)
            context_jobs.update(job_dir, stage="building task")

        real_context_path = context_path(owrap_sid)
        projects_path = target.project_path if do_protocol else None

        # Model gets transcript only; our code merges its report deterministically.
        blocks = ""
        project_section = None
        if do_context:
            blocks += CTX_CONTEXT_BLOCK
        if do_protocol:
            if target.project_path:
                if target.subproject_id:
                    record_kind = "Subproject"
                    record_id = target.subproject_id
                else:
                    record_kind = "Project"
                    record_id = target.project_id
                project_section = f"{record_kind}: {record_id}"
                blocks += CTX_PROJECT_BLOCK.format(
                    record_kind=record_kind,
                    record_id=record_id,
                )
            for repo_id in repository_paths:
                blocks += CTX_REPOSITORY_BLOCK.format(repo_id=repo_id)
        if not blocks:
            counters["transcript_cursor_ns"] = new_cursor_ns
            self._write_counters(owrap_sid, counters, ccsid)
            if touched_entries:
                self._clear_touched_entries(owrap_sid, ccsid)
            return 0
        task_content = CTX_SCOPED_TASK_TEMPLATE.format(blocks=blocks)
        if do_protocol:
            task_content += (
                "\nIf no project or repository fact is newer than this excerpt, "
                "omit its block. For an updr-only run with no updates, "
                "write exactly `# No updates`.\n"
            )

        (ctx_dir / "input.md").write_text(task_content)
        output_path = ctx_dir / "output.md"
        project_snapshot = (
            projects_path.read_bytes()
            if projects_path and projects_path.exists() else None
        )
        repository_snapshots = {
            repo_id: path.read_bytes() if path.exists() else None
            for repo_id, path in repository_paths.items()
        }

        print(
            f"ctx-worker: transcript since "
            f"{self._fmt_ts_ns(effective_cursor_ns)}..{self._fmt_ts_ns(new_cursor_ns)}",
            flush=True,
        )

        # Primary model retries once, then each fallback rung tries once.
        chain = get_model_chain(config)
        # Empty chain (no config at all): one attempt, opencode's own default.
        attempts = [chain[0], chain[0]] + chain[1:] if chain else [None]
        rc = 1
        output_text = None
        for model in attempts:
            if job_dir:
                context_jobs.update(
                    job_dir, stage="running model", model=model or "default",
                )
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

        if job_dir:
            (job_dir / "output.md").write_text(output_text)
            context_jobs.update(job_dir, stage="applying result")

        self._apply_record_output(
            output_text, real_context_path, projects_path,
            repository_paths, owrap_sid, project_snapshot, event_ns,
            repository_snapshots, project_section,
        )
        counters["transcript_cursor_ns"] = new_cursor_ns
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
            cmd_str, capture_output=True, print_output=True,
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
        sections = split_top_sections(output_text, ("Context",))
        if do_context:
            if "## Focus" not in sections.get("Context", ""):
                return False
        if do_protocol and not do_context:
            if (
                "# Project:" not in output_text
                and "# Subproject:" not in output_text
                and "# Repository:" not in output_text
                and output_text.strip() != "# No updates"
            ):
                return False
        return True

    def _apply_record_output(
        self, output_text, context_file, project_path, repository_paths,
        session_id, project_snapshot, event_ns=None,
        repository_snapshots=None, project_section=None,
    ):
        """
        Merge an explicit session's project and touched repository records.
        """
        names = ["Context"] + ([project_section] if project_section else []) + [
            f"Repository: {repo_id}" for repo_id in repository_paths
        ]
        sections = split_top_sections(output_text, tuple(names))
        if sections.get("Context"):
            self._merge_context(sections["Context"], context_file, session_id)
        if project_path and project_section and sections.get(project_section):
            self._merge_record_project(
                sections[project_section], project_path,
                project_snapshot, event_ns,
            )
        for repo_id, path in repository_paths.items():
            block = sections.get(f"Repository: {repo_id}")
            if block:
                snapshot = (
                    repository_snapshots.get(repo_id)
                    if repository_snapshots is not None else None
                )
                self._merge_record_repository(
                    block, path, event_ns, snapshot,
                )

    def _merge_record_project(
        self, block, path, original_snapshot, event_ns=None,
    ):
        """
        Update a project record while preserving its goals and notes.
        """
        with file_lock(path.with_name(path.name + ".lock")):
            if event_ns and path.exists() and path.stat().st_mtime_ns > event_ns:
                return
            text = path.read_text() if path.exists() else ""
            current_snapshot = path.read_bytes() if path.exists() else None
            status = extract_section(block, "## Status")
            if status and current_snapshot == original_snapshot:
                text = replace_section(text, "## Status", status)
            decisions = self._entry_lines(block, "## Decisions")
            if decisions:
                stamp = time.strftime("%Y-%m-%d %H:%M")
                lines = [f"- {stamp} — {line.removeprefix('- ').strip()}"
                         for line in decisions if line.startswith("- ")]
                text = merge_log_entries(
                    text, "## Decisions", lines, cap=None, prepend=True,
                    key_fn=self._record_decision_key,
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    def _merge_record_repository(
        self, block, path, event_ns=None, snapshot=None,
    ):
        """
        Add distinct architecture facts to one repository record.
        """
        with file_lock(path.with_name(path.name + ".lock")):
            if event_ns and path.exists() and path.stat().st_mtime_ns > event_ns:
                return
            if snapshot is not None and path.exists():
                if path.read_bytes() != snapshot:
                    return
            text = path.read_text() if path.exists() else ""
            for heading in (
                "## Architecture", "## Components", "## Interfaces",
                "## Environment",
            ):
                entries = [
                    line for line in self._entry_lines(block, heading)
                    if line.startswith("- ")
                ]
                if entries:
                    if event_ns:
                        text = self._replace_record_facts(
                            text, heading, entries,
                        )
                    else:
                        text = merge_log_entries(
                            text, heading, entries, cap=None,
                            key_fn=self._bullet_key,
                        )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    def _replace_record_facts(self, text, heading, entries):
        current = extract_section(text, heading)
        ordered = {}
        for line in entries:
            ordered[self._bullet_key(line)] = line
        if current:
            kept = [
                line for line in current.splitlines()[1:]
                if not (
                    line.startswith("- ")
                    and self._bullet_key(line) in ordered
                )
            ]
        else:
            kept = []
        block = "\n".join([heading] + kept + list(ordered.values()))
        return replace_section(text, heading, block)

    def _record_decision_key(self, line):
        stripped = re.sub(
            r"^-\s*\d{4}-\d{2}-\d{2}(\s+\d{2}:\d{2})?\s*—\s*", "", line,
        )
        return self._bullet_key(stripped)

    def _latest_event_ns(self, lines):
        latest = None
        for line in lines:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _ts_ns(entry.get("timestamp"))
            if ts is not None:
                latest = max(latest or ts, ts)
        return latest

    @staticmethod
    def _fmt_ts_ns(ns: int) -> str:
        """
        Render a nanosecond timestamp as UTC ISO-8601, for log messages.
        """
        if not ns:
            return "(start)"
        return datetime.fromtimestamp(
            ns / 1_000_000_000, tz=timezone.utc,
        ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

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

    def _entry_lines(self, block, heading):
        """
        Return the non-empty entry lines under `heading` within `block`,
        excluding the heading line itself.
        """
        section = extract_section(block, heading)
        if not section:
            return []
        return [line for line in section.splitlines()[1:] if line.strip()]

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

    def _last_attach_ts_ns(self, lines: list, owrap_sid: str) -> int:
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
            ts = _ts_ns(entry.get("timestamp"))
            if ts is not None:
                latest = max(latest, ts)
        return latest

    def _extract_excerpt_lines(self, lines: list, cursor_ns: int) -> list:
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
                    skip_update_turn = self._is_context_update_request(prompt)
            entry_ts = _ts_ns(entry.get("timestamp"))
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
                                    and not self._is_context_update_command(cmd)):
                                texts.append(f"$ {cmd}")
                                pending[block.get("id")] = name
                        elif name in ("Edit", "Write", "Read"):
                            path = tool_input.get("file_path", "")
                            if path and (not skip_update_turn or name != "Read"):
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

    def _extract_codex_excerpt_lines(self, lines: list, cursor_ns: int) -> list:
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
                    skip_update_turn = self._is_context_update_request(message)
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
                        skip_update_turn = self._is_context_update_request(message)
            entry_ts = _ts_ns(entry.get("timestamp"))
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
                             and self._is_context_update_command(shlex.join(command)))
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

    def _read_counters(self, session_id: str, ccsid: str) -> dict:
        p = session_ctx_counters_path(session_id, ccsid)
        if p.exists():
            try:
                with open(p) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _write_counters(self, session_id: str, data: dict, ccsid: str):
        p = session_ctx_counters_path(session_id, ccsid)
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

    @staticmethod
    def _is_context_update_request(text: str) -> bool:
        command = r"(?:--uall|--ctx|--updr|owrap\s+(?:ctx|updr))\b"
        return bool(
            re.search(rf"^\s*`?{command}", text, re.IGNORECASE)
            or re.search(
                rf"\b(?:run|do|try|execute|rerun|another)\b[^\n]{{0,80}}{command}",
                text, re.IGNORECASE,
            )
        )

    @staticmethod
    def _is_context_update_command(command: str) -> bool:
        return bool(re.search(
            r"(?:^|[/\s])owrap\s+(?:ctx|updr|ctx-hook|ctx-worker)\b",
            command,
        ))

    @staticmethod
    def _has_recognized_transcript_entries(
        lines: list, cursor_ns: int, source: str,
    ) -> bool:
        for line in lines:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            entry_ts = _ts_ns(entry.get("timestamp"))
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
        if not owrap_sid and ccsid:
            owrap_sid = owrap_sid_for_codex_session_id(ccsid)
            if owrap_sid:
                hook_data["source"] = "codex"

        if not owrap_sid:
            print("{}")
            sys.exit(0)

        ctx_dir = session_ctx_dir(owrap_sid, ccsid)
        ctx_dir.mkdir(parents=True, exist_ok=True)
        job_dir = context_jobs.create(owrap_sid, ccsid, "ctx+updr")
        hook_data["job_dir"] = str(job_dir)
        input_path = job_dir / "hook.json"
        input_path.write_text(json.dumps(hook_data))

        log_path = job_dir / "output.log"
        log_fd = open(str(log_path), "a")
        try:
            process = subprocess.Popen(
                [sys.executable, "-m", "owrap.runner", "ctx-worker",
                 "--input", str(input_path)],
                stdout=log_fd,
                stderr=log_fd,
                start_new_session=True,
                close_fds=True,
                cwd=str(Path(__file__).resolve().parents[2]),
            )
        except Exception:
            context_jobs.finish(job_dir, 1)
            raise
        finally:
            log_fd.close()
        if isinstance(process.pid, int):
            context_jobs.update(job_dir, pid=process.pid)

        print("{}")
        sys.exit(0)
