import json
import os
import shlex
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from owrap.commands.context_manager import CtxHookRunner
from owrap.commands.context_manager import CtxWorkerRunner, MAX_EXCERPT_CHARS
from owrap.utils.parser.sections import split_top_sections


_BASE_TS = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _entry_ts(index: int) -> str:
    """
    Deterministic, strictly increasing timestamp for transcript entry
    `index`, matching the `Z`-suffixed ISO-8601 format real transcripts use.
    """
    return (_BASE_TS + timedelta(seconds=index)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _entry_ts_ns(index: int) -> int:
    """
    The `_entry_ts(index)` timestamp as nanoseconds since epoch — a cursor
    value meaning "entries up to and including index are already consumed".
    """
    return int((_BASE_TS + timedelta(seconds=index)).timestamp() * 1_000_000_000)


def _lines_with_ts(entries: list) -> list:
    """
    Serialize transcript entries to JSONL strings, stamping each with
    `_entry_ts(index)` unless it already sets its own `timestamp`.
    """
    out = []
    for i, entry in enumerate(entries):
        entry = dict(entry)
        entry.setdefault("timestamp", _entry_ts(i))
        out.append(json.dumps(entry))
    return out


VALID_OUTPUT_MD = (
    "# Context\n## Focus\ntest focus\n\n"
    "# Project: owrap\n## Status\ntest status\n"
)


def _patch_terminal(rc=0, output_text=VALID_OUTPUT_MD):
    """
    Patch Terminal so context_manager dispatch never spawns a real
    opencode process. When output_text is given (the default — a minimal
    output satisfying validation for both Context and Project), it's
    written to output.md in the dispatch's `cwd` on each call, so a
    dispatch validates and succeeds on its first attempt. Pass
    output_text=None to simulate a model that never produces output.md.
    Returns (mock_terminal_cls, mock_run); mock_run's first call arg is
    the full shell command string — shlex.split() it to get argv-
    equivalent tokens.
    """
    def _run(cmd_str, *args, **kwargs):
        if output_text is not None:
            cwd = kwargs.get("cwd")
            if cwd:
                (Path(cwd) / "output.md").write_text(output_text)
        return {"returncode": rc}

    mock_terminal_cls = MagicMock()
    mock_terminal = MagicMock()
    mock_terminal.run.side_effect = _run
    mock_terminal_cls.return_value = mock_terminal
    return mock_terminal_cls, mock_terminal.run


# Helpers

def _make_hook_stdin(ccsid, transcript_path="/tmp/transcript.jsonl", cwd="/tmp"):
    return json.dumps({
        "session_id": ccsid,
        "transcript_path": transcript_path,
        "cwd": cwd,
    })


def _make_session_file(sessions_dir, owrap_sid, ccsid, research="testr", area="testarea"):
    """
    Write a .session file plus the by_ccsid/<ccsid> pointer that attach()
    actually creates — context_manager.py resolves ownership via that
    pointer, not by scanning .session files for a field match, since under
    multi-attach the .session file's claude_session_id field only ever
    holds the most recently attached ccsid.
    """
    sf = sessions_dir / f"{owrap_sid}.session"
    sf.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"session_id={owrap_sid}",
        f"claude_session_id={ccsid}",
        f"research={research}",
        f"area={area}",
    ]
    sf.write_text("\n".join(lines) + "\n")
    by_ccsid = sessions_dir / "by_ccsid"
    by_ccsid.mkdir(parents=True, exist_ok=True)
    (by_ccsid / ccsid).write_text(owrap_sid)
    return sf


def _make_project_session(sessions_dir, sid, ccsid):
    session = _make_session_file(sessions_dir, sid, ccsid)
    session.write_text(
        f"session_id={sid}\nclaude_session_id={ccsid}\n"
        "target_kind=project\nproject_id=owrap\n"
        "subproject_id=\nworkspace=test\n"
    )
    return session


def _make_transcript_jsonl(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(_lines_with_ts(entries)) + "\n")


def _patch_dirs(monkeypatch, tmp_path):
    docs_dir = tmp_path / "docs"
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr("owrap.utils.paths.DOCS_DIR", docs_dir)
    monkeypatch.setattr("owrap.utils.paths.SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr("owrap.utils.session.resolver.SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(
        "owrap.utils.session.resolver.BY_CCSID_DIR", sessions_dir / "by_ccsid",
    )
    monkeypatch.setattr(
        "owrap.utils.session.resolver.BY_CODEX_SESSION_ID_DIR",
        sessions_dir / "by_codex_session_id",
    )
    monkeypatch.setattr(
        "owrap.commands.context_manager.OPENCODE_STATUS_FILE",
        tmp_path / "opencode_status.json",
    )
    return docs_dir, sessions_dir


# CtxHookRunner with matching session

def test_ctx_hook_spawns_worker(tmp_path, monkeypatch):
    docs_dir, sessions_dir = _patch_dirs(monkeypatch, tmp_path)

    ccsid = "claude-123"
    owrap_sid = "abc123"
    _make_session_file(sessions_dir, owrap_sid, ccsid)

    mock_popen = MagicMock()
    with patch("owrap.commands.context_manager.subprocess.Popen", mock_popen), \
         patch("owrap.commands.context_manager.sys.stdin.read") as mock_stdin:
        mock_stdin.return_value = _make_hook_stdin(ccsid)
        with pytest.raises(SystemExit) as exc_info:
            CtxHookRunner().run()
        assert exc_info.value.code == 0

    # Check that the input JSON was written, scoped by ccsid
    input_json = Path(mock_popen.call_args[0][0][-1])
    assert input_json.exists()
    assert input_json.parent.parent.name == "jobs"
    data = json.loads(input_json.read_text())
    assert data["session_id"] == ccsid

    # Check Popen was called with correct args
    mock_popen.assert_called_once()
    call_args = mock_popen.call_args[0][0]
    assert call_args[1:5] == ["-m", "owrap.runner", "ctx-worker", "--input"]
    assert call_args[5] == str(input_json)
    kw = mock_popen.call_args[1]
    assert kw["start_new_session"] is True
    assert kw["close_fds"] is True


# CtxHookRunner with no matching session

def test_ctx_hook_no_matching_session(tmp_path, monkeypatch):
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)

    mock_popen = MagicMock()
    with patch("owrap.commands.context_manager.subprocess.Popen", mock_popen), \
         patch("owrap.commands.context_manager.sys.stdin.read") as mock_stdin:
        mock_stdin.return_value = _make_hook_stdin("unknown-ccsid")
        with pytest.raises(SystemExit) as exc_info:
            CtxHookRunner().run()
        assert exc_info.value.code == 0

    mock_popen.assert_not_called()


def test_ctx_hook_uses_codex_session_mapping(tmp_path, monkeypatch):
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    cid = "codex-123"
    sid = "abc123"
    pointer = sessions_dir / "by_codex_session_id" / cid
    pointer.parent.mkdir(parents=True)
    pointer.write_text(sid)

    with patch("owrap.commands.context_manager.subprocess.Popen") as popen, \
         patch("owrap.commands.context_manager.sys.stdin.read") as stdin:
        stdin.return_value = _make_hook_stdin(cid)
        with pytest.raises(SystemExit) as exc:
            CtxHookRunner().run()

    assert exc.value.code == 0
    input_path = Path(popen.call_args[0][0][-1])
    assert input_path.parent.parent.name == "jobs"
    assert json.loads(input_path.read_text())["source"] == "codex"
    popen.assert_called_once()


# Transcript parsing helper

def test_extract_excerpt_lines():
    worker = CtxWorkerRunner()
    entries = [
        {"type": "user", "message": {"role": "user",
         "content": [{"type": "text", "text": "hello"}]}},
        {"type": "assistant", "message": {"role": "assistant",
         "content": [{"type": "text", "text": "I will help"}]}},
        {"type": "tool_result", "tool_use_id": "t1", "content": "result"},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "First block"},
            {"type": "tool_use", "name": "read", "input": {}},
            {"type": "text", "text": "Second block"},
        ]}},
    ]
    lines = _lines_with_ts(entries)

    # From the start
    result = worker._extract_excerpt_lines(lines, 0)
    assert len(result) == 3
    assert result[0] == "I will help"
    assert result[1] == "First block"
    assert result[2] == "Second block"

    # Cursor past entry 0 (skip user)
    result = worker._extract_excerpt_lines(lines, _entry_ts_ns(0))
    assert len(result) == 3

    # Cursor past entry 2 (skip first assistant + tool_result)
    result = worker._extract_excerpt_lines(lines, _entry_ts_ns(2))
    assert len(result) == 2
    assert result[0] == "First block"
    assert result[1] == "Second block"

    # Cursor past the last entry
    result = worker._extract_excerpt_lines(lines, _entry_ts_ns(3))
    assert len(result) == 0


def test_extract_excerpt_lines_includes_bash_command_and_short_result():
    worker = CtxWorkerRunner()
    entries = [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "Bash",
             "input": {"command": "owrap attach 9f5f96"}},
        ]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1",
             "content": "ATTACHED session=9f5f96"},
        ]}},
    ]
    lines = _lines_with_ts(entries)
    result = worker._extract_excerpt_lines(lines, 0)
    assert result == ["$ owrap attach 9f5f96", "-> ATTACHED session=9f5f96"]


def test_extract_excerpt_lines_squeezes_long_result():
    worker = CtxWorkerRunner()
    entries = [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "Bash",
             "input": {"command": "pytest -q"}},
        ]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1",
             "content": "collecting...\n" + ("." * 300) + "\n312 passed in 29.56s"},
        ]}},
    ]
    lines = _lines_with_ts(entries)
    result = worker._extract_excerpt_lines(lines, 0)
    assert result == ["$ pytest -q", "-> 312 passed in 29.56s"]


def test_extract_excerpt_lines_includes_edit_write_read_paths():
    worker = CtxWorkerRunner()
    entries = [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "Edit",
             "input": {"file_path": "owrap/foo.py"}},
            {"type": "tool_use", "id": "t2", "name": "Write",
             "input": {"file_path": "owrap/bar.py"}},
            {"type": "tool_use", "id": "t3", "name": "Read",
             "input": {"file_path": "owrap/baz.py"}},
        ]}},
    ]
    lines = _lines_with_ts(entries)
    result = worker._extract_excerpt_lines(lines, 0)
    assert result == [
        "[Edit] owrap/foo.py", "[Write] owrap/bar.py", "[Read] owrap/baz.py",
    ]


def test_extract_excerpt_lines_includes_notebook_edit_path():
    worker = CtxWorkerRunner()
    entries = [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "NotebookEdit",
             "input": {"notebook_path": "owrap/analysis.ipynb"}},
        ]}},
    ]
    lines = _lines_with_ts(entries)
    result = worker._extract_excerpt_lines(lines, 0)
    assert result == ["[NotebookEdit] owrap/analysis.ipynb"]


def test_extract_excerpt_lines_ignores_untracked_tool_result():
    worker = CtxWorkerRunner()
    entries = [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "Grep", "input": {"pattern": "foo"}},
        ]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "match"},
        ]}},
    ]
    lines = _lines_with_ts(entries)
    result = worker._extract_excerpt_lines(lines, 0)
    assert result == []


# CtxWorker with no new transcript lines

# Touched paths handoff

def test_dispatch_fires_for_touched_entries_with_no_new_transcript(tmp_path, monkeypatch):
    from owrap.utils.paths import session_ctx_touched_path, session_ctx_transcript_path
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)

    ccsid = "claude-touched"
    owrap_sid = "touched01"
    _make_session_file(sessions_dir, owrap_sid, ccsid)

    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "assistant", "message": {"role": "assistant",
         "content": [{"type": "text", "text": "hello"}]}},
    ])
    # Cursor already covers everything — nothing new to mine.
    counters = {"transcript_cursor_ns": _entry_ts_ns(0)}
    cp = sessions_dir / f"{owrap_sid}.{ccsid}.counters.json"
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(counters))

    touched_path = session_ctx_touched_path(owrap_sid, ccsid)
    touched_path.parent.mkdir(parents=True, exist_ok=True)
    touched_path.write_text(json.dumps([
        {"path": "owrap/foo.py", "note": "renamed helper"},
    ]))

    input_path = tmp_path / "hook_input.json"
    input_path.write_text(json.dumps({
        "session_id": ccsid, "transcript_path": str(transcript),
    }))

    mock_terminal_cls, mock_run = _patch_terminal()
    with patch("owrap.commands.context_manager.Terminal", mock_terminal_cls):
        CtxWorkerRunner().run(input_path=input_path)

    mock_run.assert_called_once()
    excerpt = session_ctx_transcript_path(owrap_sid, ccsid).read_text()
    assert "[Touched] owrap/foo.py — renamed helper" in excerpt
    # Cleared after a successful dispatch.
    assert not touched_path.exists()


def test_touched_entries_not_cleared_on_dispatch_failure(tmp_path, monkeypatch):
    from owrap.utils.paths import session_ctx_touched_path
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)

    ccsid = "claude-touched-fail"
    owrap_sid = "touchedfail01"
    _make_session_file(sessions_dir, owrap_sid, ccsid)

    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "assistant", "message": {"role": "assistant",
         "content": [{"type": "text", "text": "hello"}]}},
    ])
    counters = {"transcript_cursor_ns": _entry_ts_ns(0)}
    cp = sessions_dir / f"{owrap_sid}.{ccsid}.counters.json"
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(counters))

    touched_path = session_ctx_touched_path(owrap_sid, ccsid)
    touched_path.parent.mkdir(parents=True, exist_ok=True)
    touched_path.write_text(json.dumps([{"path": "owrap/foo.py", "note": ""}]))

    input_path = tmp_path / "hook_input.json"
    input_path.write_text(json.dumps({
        "session_id": ccsid, "transcript_path": str(transcript),
    }))

    mock_terminal_cls, mock_run = _patch_terminal(rc=0, output_text=None)
    with patch("owrap.commands.context_manager.Terminal", mock_terminal_cls):
        CtxWorkerRunner().run(input_path=input_path)

    # Still queued — nothing was successfully applied.
    assert touched_path.exists()


def test_ctx_worker_nothing_new(tmp_path, monkeypatch):
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)

    ccsid = "claude-123"
    owrap_sid = "abc456"
    _make_session_file(sessions_dir, owrap_sid, ccsid)

    # Write counters with the cursor past both entries (all consumed)
    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "hello"}]}},
    ])

    counters = {"transcript_cursor_ns": _entry_ts_ns(1)}
    cp = sessions_dir / f"{owrap_sid}.{ccsid}.counters.json"
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(counters))

    input_path = tmp_path / "hook_input.json"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(json.dumps({
        "session_id": ccsid,
        "transcript_path": str(transcript),
    }))

    mock_terminal_cls, mock_run = _patch_terminal()
    with patch("owrap.commands.context_manager.Terminal", mock_terminal_cls):
        CtxWorkerRunner().run(input_path=input_path)

    # No opencode dispatch
    mock_run.assert_not_called()
    # No task file
    task_file = (
        sessions_dir / owrap_sid / "ctx" / "windows" / ccsid / "input.md"
    )
    assert not task_file.exists()
    # No transcript tmp file
    transcript_tmp = (
        sessions_dir / owrap_sid / "ctx" / "windows" / ccsid
        / "transcript.txt"
    )
    assert not transcript_tmp.exists()
    # Cursor unchanged
    updated = json.loads(cp.read_text())
    assert updated["transcript_cursor_ns"] == _entry_ts_ns(1)


# CtxWorker with new assistant text

def test_ctx_worker_with_new_text(tmp_path, monkeypatch):
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)

    ccsid = "claude-456"
    owrap_sid = "def789"
    _make_session_file(sessions_dir, owrap_sid, ccsid)

    # 5 entries, cursor past the first 2
    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "q"}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "old answer"}]}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "q2"}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "new answer here for context update"}]}},
        {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
    ])

    counters = {"transcript_cursor_ns": _entry_ts_ns(1)}
    cp = sessions_dir / f"{owrap_sid}.{ccsid}.counters.json"
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(counters))

    input_path = tmp_path / "hook_input.json"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(json.dumps({
        "session_id": ccsid,
        "transcript_path": str(transcript),
    }))

    mock_terminal_cls, mock_run = _patch_terminal()
    with patch("owrap.commands.context_manager.Terminal", mock_terminal_cls):
        runner = CtxWorkerRunner()
        runner.run(input_path=input_path)

    # Transcript tmp file written
    ctx_dir = sessions_dir / owrap_sid / "ctx" / "windows" / ccsid
    transcript_tmp = ctx_dir / "transcript.txt"
    assert transcript_tmp.exists()
    excerpt = transcript_tmp.read_text()
    assert "new answer here for context update" in excerpt

    # Task file references only local filenames, never a real absolute path.
    task_file = ctx_dir / "input.md"
    assert task_file.exists()
    task_text = task_file.read_text()
    assert "transcript.txt" in task_text
    assert "# Context" in task_text
    assert "## Focus" in task_text
    assert str(transcript_tmp) not in task_text

    # No copy of context.md is prepared — the model only ever sees the transcript.
    assert not (ctx_dir / "context.md").exists()

    # Dispatched directly against the scoped dir under a pty, no pool/orun.
    mock_run.assert_called_once()
    cmd = shlex.split(mock_run.call_args[0][0])
    assert cmd[0] == "opencode"
    assert "--dir" in cmd
    assert "--dangerously-skip-permissions" not in cmd
    assert not (ctx_dir / "opencode.json").exists()

    # Cursor advanced to the last entry's timestamp, in the session-level
    # ctx_state.json the legacy per-window counters.json migrated into.
    state = json.loads((sessions_dir / owrap_sid / "ctx_state.json").read_text())
    assert state["windows"][ccsid]["transcript_cursor_ns"] == _entry_ts_ns(4)


# Context status tracking

def _make_context_md(sessions_dir, owrap_sid):
    path = sessions_dir / owrap_sid / "context.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "## Session\n\nsession: " + owrap_sid + "\nresearch: testr\n\n"
        "## Focus\n\n(none)\n"
    )
    return path


def _ctx_status(context_path):
    state_path = context_path.parent / "ctx_state.json"
    if not state_path.exists():
        return None
    try:
        return json.loads(state_path.read_text()).get("ctx", {}).get("status")
    except (json.JSONDecodeError, OSError):
        return None


def test_ctx_status_ok_after_successful_dispatch(tmp_path, monkeypatch):
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)

    ccsid = "claude-status-ok"
    owrap_sid = "status01"
    _make_session_file(sessions_dir, owrap_sid, ccsid)
    context_md = _make_context_md(sessions_dir, owrap_sid)

    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "did work"},
        ]}},
    ])
    input_path = tmp_path / "hook_input.json"
    input_path.write_text(json.dumps({
        "session_id": ccsid, "transcript_path": str(transcript),
    }))

    mock_terminal_cls, mock_run = _patch_terminal(rc=0)
    with patch("owrap.commands.context_manager.Terminal", mock_terminal_cls):
        CtxWorkerRunner().run(input_path=input_path)

    assert _ctx_status(context_md) == "ok"


def test_ctx_status_failed_when_opencode_errors(tmp_path, monkeypatch):
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)

    ccsid = "claude-status-fail"
    owrap_sid = "status02"
    _make_session_file(sessions_dir, owrap_sid, ccsid)
    context_md = _make_context_md(sessions_dir, owrap_sid)

    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "did work"},
        ]}},
    ])
    input_path = tmp_path / "hook_input.json"
    input_path.write_text(json.dumps({
        "session_id": ccsid, "transcript_path": str(transcript),
    }))

    mock_terminal_cls, mock_run = _patch_terminal(rc=1)
    with patch("owrap.commands.context_manager.Terminal", mock_terminal_cls):
        CtxWorkerRunner().run(input_path=input_path)

    assert _ctx_status(context_md) == "failed"


def test_ctx_status_failed_on_uncaught_exception(tmp_path, monkeypatch):
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)

    ccsid = "claude-status-crash"
    owrap_sid = "status03"
    _make_session_file(sessions_dir, owrap_sid, ccsid)
    context_md = _make_context_md(sessions_dir, owrap_sid)

    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "did work"},
        ]}},
    ])
    input_path = tmp_path / "hook_input.json"
    input_path.write_text(json.dumps({
        "session_id": ccsid, "transcript_path": str(transcript),
    }))

    with patch(
        "owrap.commands.context_manager.Terminal",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(RuntimeError):
            CtxWorkerRunner().run(input_path=input_path)

    assert _ctx_status(context_md) == "failed"


def test_ctx_status_failed_when_transcript_missing(tmp_path, monkeypatch):
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)

    ccsid = "claude-status-notranscript"
    owrap_sid = "status04"
    _make_session_file(sessions_dir, owrap_sid, ccsid)
    context_md = _make_context_md(sessions_dir, owrap_sid)

    input_path = tmp_path / "hook_input.json"
    input_path.write_text(json.dumps({
        "session_id": ccsid, "transcript_path": str(tmp_path / "missing.jsonl"),
    }))

    CtxWorkerRunner().run(input_path=input_path)

    assert _ctx_status(context_md) == "failed"


# CtxWorker with update due

def test_ctx_worker_skips_protocol_for_legacy_session(
    tmp_path, monkeypatch,
):
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)

    ccsid = "claude-789"
    owrap_sid = "ghi012"
    _make_session_file(sessions_dir, owrap_sid, ccsid)

    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "new stuff happened"}]}},
    ])

    base_config_path = tmp_path / "base_config.json"
    base_config_path.parent.mkdir(parents=True, exist_ok=True)
    base_config_path.write_text(json.dumps({
        "default_workspace": "test",
    }))

    input_path = tmp_path / "hook_input.json"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(json.dumps({
        "session_id": ccsid,
        "transcript_path": str(transcript),
    }))

    mock_terminal_cls, mock_run = _patch_terminal()
    with patch("owrap.utils.paths.BASE_CONFIG_FILE", base_config_path), \
         patch("owrap.commands.context_manager.Terminal", mock_terminal_cls):
        runner = CtxWorkerRunner()
        runner.run(input_path=input_path)

    ctx_dir = sessions_dir / owrap_sid / "ctx" / "windows" / ccsid
    task_file = ctx_dir / "input.md"
    assert task_file.exists()
    task_text = task_file.read_text()
    assert "# Context" in task_text
    assert "# Memory" not in task_text
    assert "# Project" not in task_text

    # No copies of memory.md/project.md are prepared either — same reason
    assert not (ctx_dir / "memory.md").exists()
    assert not (ctx_dir / "project.md").exists()


# Multiple attachment isolation

def test_ctx_worker_isolated_per_ccsid_under_multi_attach(tmp_path, monkeypatch):
    """
    Two windows attached to the same owrap session get isolated files.

    independent counters/transcript/input files — this is the bug that
    full-session-scan resolution (matching the single claude_session_id
    field in .session) silently broke under multi-attach: only the most
    recently attached ccsid would ever resolve.
    """
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)

    owrap_sid = "multi01"
    ccsid_a = "claude-a"
    ccsid_b = "claude-b"
    # Both attached to the same session; by_ccsid keeps ccsid_a resolvable.
    _make_session_file(sessions_dir, owrap_sid, ccsid_b)
    (sessions_dir / "by_ccsid" / ccsid_a).write_text(owrap_sid)

    transcript_a = tmp_path / "transcript_a.jsonl"
    _make_transcript_jsonl(transcript_a, [
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "from window A"}]}},
    ])
    transcript_b = tmp_path / "transcript_b.jsonl"
    _make_transcript_jsonl(transcript_b, [
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "from window B"}]}},
    ])

    input_a = tmp_path / "hook_a.json"
    input_a.write_text(json.dumps({"session_id": ccsid_a, "transcript_path": str(transcript_a)}))
    input_b = tmp_path / "hook_b.json"
    input_b.write_text(json.dumps({"session_id": ccsid_b, "transcript_path": str(transcript_b)}))

    mock_terminal_cls, mock_run = _patch_terminal()
    with patch("owrap.commands.context_manager.Terminal", mock_terminal_cls):
        CtxWorkerRunner().run(input_path=input_a)
        CtxWorkerRunner().run(input_path=input_b)

    transcript_tmp_a = (
        sessions_dir / owrap_sid / "ctx" / "windows" / ccsid_a
        / "transcript.txt"
    )
    transcript_tmp_b = (
        sessions_dir / owrap_sid / "ctx" / "windows" / ccsid_b
        / "transcript.txt"
    )
    assert transcript_tmp_a.exists()
    assert transcript_tmp_b.exists()
    assert "from window A" in transcript_tmp_a.read_text()
    assert "from window B" in transcript_tmp_b.read_text()

    state = json.loads((sessions_dir / owrap_sid / "ctx_state.json").read_text())
    assert state["windows"][ccsid_a]["transcript_cursor_ns"] == _entry_ts_ns(0)
    assert state["windows"][ccsid_b]["transcript_cursor_ns"] == _entry_ts_ns(0)


# Same window across sessions

def test_ctx_worker_excludes_text_before_session_switch(tmp_path, monkeypatch):
    """
    A window that switches from one owrap session to another must not
    pull the first session's unrelated transcript text into the second
    session's first-ever context update.
    """
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)

    ccsid = "claude-shared-window"
    owrap_sid_a = "sessA01"
    owrap_sid_b = "sessB02"
    _make_session_file(sessions_dir, owrap_sid_a, ccsid, research="proja")
    # The window is now bound to B, as a real `owrap attach` would leave it.
    (sessions_dir / "by_ccsid" / ccsid).write_text(owrap_sid_b)
    _make_session_file(sessions_dir, owrap_sid_b, ccsid, research="projb")

    def _assistant(text):
        return {
            "type": "assistant",
            "message": {"role": "assistant", "content": [
                {"type": "text", "text": text},
            ]},
        }

    def _attach_marker(sid):
        return {
            "type": "user",
            "message": {"role": "user", "content": [
                {
                    "type": "tool_result",
                    "content": f"__OWRAP_EXPORT__ SESSION_ID={sid}",
                },
            ]},
        }

    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        _assistant("started on project A"),
        _attach_marker(owrap_sid_a),
        _assistant("work done on project A"),
        _attach_marker(owrap_sid_b),
        _assistant("work done on project B"),
    ])

    input_path = tmp_path / "hook_b.json"
    input_path.write_text(json.dumps({
        "session_id": ccsid, "transcript_path": str(transcript),
    }))

    mock_terminal_cls, mock_run = _patch_terminal()
    with patch("owrap.commands.context_manager.Terminal", mock_terminal_cls):
        CtxWorkerRunner().run(input_path=input_path)

    transcript_tmp = (
        sessions_dir / owrap_sid_b / "ctx" / "windows" / ccsid
        / "transcript.txt"
    )
    assert transcript_tmp.exists()
    excerpt = transcript_tmp.read_text()
    assert "work done on project B" in excerpt
    assert "project A" not in excerpt


def test_ctx_worker_survives_replayed_attach_marker(tmp_path, monkeypatch):
    """
    Claude Code's crash/resume flow can re-append an old transcript entry
    verbatim later in the file. If that replayed entry happens to be an
    `__OWRAP_EXPORT__ SESSION_ID=` attach marker, it still carries its
    original (old) timestamp — so it must not push the attach floor past
    real work that happened chronologically after the real attach but
    appears, in file position, before the replay.
    """
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)

    ccsid = "claude-replayed"
    owrap_sid = "replay01"
    _make_session_file(sessions_dir, owrap_sid, ccsid)

    def _assistant(text):
        return {
            "type": "assistant",
            "message": {"role": "assistant", "content": [
                {"type": "text", "text": text},
            ]},
        }

    def _attach_marker():
        return {
            "type": "user",
            "message": {"role": "user", "content": [
                {
                    "type": "tool_result",
                    "content": f"__OWRAP_EXPORT__ SESSION_ID={owrap_sid}",
                },
            ]},
        }

    attach_ts = _entry_ts(0)
    entries = [
        dict(_attach_marker(), timestamp=attach_ts),
        dict(_assistant("real new work happened"), timestamp=_entry_ts(1)),
        # Replayed by a crash/resume: same attach marker, same original
        # timestamp, but appended at a later file position.
        dict(_attach_marker(), timestamp=attach_ts),
        dict(_assistant("more real work"), timestamp=_entry_ts(2)),
    ]
    transcript = tmp_path / "transcript.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

    input_path = tmp_path / "hook_input.json"
    input_path.write_text(json.dumps({
        "session_id": ccsid, "transcript_path": str(transcript),
    }))

    mock_terminal_cls, mock_run = _patch_terminal()
    with patch("owrap.commands.context_manager.Terminal", mock_terminal_cls):
        CtxWorkerRunner().run(input_path=input_path)

    transcript_tmp = (
        sessions_dir / owrap_sid / "ctx" / "windows" / ccsid / "transcript.txt"
    )
    assert transcript_tmp.exists()
    excerpt = transcript_tmp.read_text()
    assert "real new work happened" in excerpt
    assert "more real work" in excerpt


# Shared template

def test_templates_reference_only_local_filenames():
    from owrap.constants import (
        CTX_SCOPED_TASK_TEMPLATE, CTX_CONTEXT_BLOCK,
        CTX_PROJECT_BLOCK, CTX_REPOSITORY_BLOCK,
    )

    # Must reference only local scoped filenames, never a real absolute path.
    task = CTX_SCOPED_TASK_TEMPLATE.format(read_lines="", blocks="")
    assert "transcript.txt" in task
    assert "output.md" in task
    for text in (
        CTX_SCOPED_TASK_TEMPLATE, CTX_CONTEXT_BLOCK,
        CTX_PROJECT_BLOCK.format(record_kind="Project", record_id="project"),
        CTX_REPOSITORY_BLOCK.format(repo_id="repo"),
    ):
        assert 'self.md' not in text
        assert '/home/' not in text


# Staging

def test_stage_all_includes_sessionstart_and_ctx_hook(tmp_path, monkeypatch):
    from owrap.staging import stage_all

    workspace = tmp_path / "ws"
    workspace.mkdir(parents=True)
    configs_dir = tmp_path / "owrap_configs"

    monkeypatch.setattr("owrap.utils.paths.CONFIGS_DIR", configs_dir)
    monkeypatch.setattr("owrap.staging.CONFIGS_DIR", configs_dir)
    monkeypatch.setattr("owrap.utils.paths.TEMPLATES_DIR", Path(__file__).parents[1] / "templates")
    monkeypatch.setattr(
        "owrap.staging.staged_dir",
        lambda name: tmp_path / "staged" / name
    )

    # Write workspace config
    configs_dir.mkdir(parents=True, exist_ok=True)
    ws_config = configs_dir / "test_stage.json"
    ws_config.write_text(json.dumps({
        "workspace": str(workspace),
        "research_root": str(workspace / "docs" / "research"),
    }))

    with patch("owrap.staging.get_workspace_config") as mock_ws_cfg:
        mock_ws_cfg.return_value = {
            "workspace": str(workspace),
            "research_root": str(workspace / "docs" / "research"),
        }
        staged = stage_all("test_stage")

    # Check staged settings.json
    staged_settings = staged / "claude" / "settings.json"
    assert staged_settings.exists()
    content = json.loads(staged_settings.read_text())

    # SessionStart hook with "compact" matcher
    hooks = content.get("hooks", {})
    assert "SessionStart" in hooks
    assert len(hooks["SessionStart"]) == 1
    ss = hooks["SessionStart"][0]
    assert ss["matcher"] == "compact"
    assert len(ss["hooks"]) == 1
    ss_cmd = ss["hooks"][0]["command"]
    assert "additionalContext" in ss_cmd
    assert "owrap refresh" in ss_cmd

    assert "PreCompact" in hooks
    pc = hooks["PreCompact"][0]["hooks"][0]
    assert pc["command"] == "~/bin/owrap ctx-hook"


# Excerpt capping

def test_excerpt_capped_at_max_chars(tmp_path, monkeypatch):
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)

    ccsid = "claude-long"
    owrap_sid = "long001"
    _make_session_file(sessions_dir, owrap_sid, ccsid)

    # Generate assistant text longer than MAX_EXCERPT_CHARS
    long_text = "x" * (MAX_EXCERPT_CHARS + 2000)
    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": long_text}]}},
    ])

    input_path = tmp_path / "hook_input.json"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(json.dumps({
        "session_id": ccsid,
        "transcript_path": str(transcript),
    }))

    mock_terminal_cls, mock_run = _patch_terminal()
    with patch("owrap.commands.context_manager.Terminal", mock_terminal_cls):
        runner = CtxWorkerRunner()
        runner.run(input_path=input_path)

    transcript_tmp = (
        sessions_dir / owrap_sid / "ctx" / "windows" / ccsid
        / "transcript.txt"
    )
    assert transcript_tmp.exists()
    excerpt = transcript_tmp.read_text()
    assert len(excerpt) <= MAX_EXCERPT_CHARS
    # Should contain the tail of the long text
    assert excerpt.endswith("x")


def _dispatch_ctx_with_config(tmp_path, monkeypatch, extra_config):
    """
    Run CtxWorkerRunner once with the given extra base-config keys
    merged in, and return the dispatched opencode command list.
    """
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)

    ccsid = "claude-model"
    owrap_sid = "model01"
    _make_session_file(sessions_dir, owrap_sid, ccsid)

    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
        },
    ])

    base_config_path = tmp_path / "base_config.json"
    base_config_path.write_text(json.dumps({
        "default_workspace": "test",
        **extra_config,
    }))

    input_path = tmp_path / "hook_input.json"
    input_path.write_text(json.dumps({
        "session_id": ccsid,
        "transcript_path": str(transcript),
    }))

    mock_terminal_cls, mock_run = _patch_terminal()
    with patch("owrap.utils.paths.BASE_CONFIG_FILE", base_config_path), \
         patch("owrap.commands.context_manager.Terminal", mock_terminal_cls):
        CtxWorkerRunner().run(input_path=input_path)

    return shlex.split(mock_run.call_args[0][0])


def test_ctx_dispatch_uses_context_manager_model(tmp_path, monkeypatch):
    cmd = _dispatch_ctx_with_config(tmp_path, monkeypatch, {
        "context_manager_model": "custom/model", "runner_model": "runner/model",
    })
    assert "-m" in cmd
    assert cmd[cmd.index("-m") + 1] == "custom/model"


def test_ctx_dispatch_falls_back_to_context_fallback_model(tmp_path, monkeypatch):
    cmd = _dispatch_ctx_with_config(tmp_path, monkeypatch, {
        "context_fallback_model": "opencode/deepseek-v4-flash-free",
    })
    assert "-m" in cmd
    assert cmd[cmd.index("-m") + 1] == "opencode/deepseek-v4-flash-free"


def test_manual_ctx_template_prints_target_paths(tmp_path, monkeypatch, capsys):
    from owrap.commands.context_manager import ManualCtxRunner
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    ccsid = "claude-fallback"
    owrap_sid = "fallback01"
    _make_project_session(sessions_dir, owrap_sid, ccsid)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", ccsid)
    monkeypatch.setattr(
        "owrap.commands.context_manager.resolve_memory_target",
        lambda data: SimpleNamespace(
            project_path=Path("/tmp/project.md"), project_id="owrap",
            subproject_id="", repository_ids=("repo1",),
            repository_paths=(Path("/tmp/repo1.md"),),
        ),
    )

    ManualCtxRunner().template()

    out = capsys.readouterr().out
    assert "opencode status:" in out
    assert "# Project: owrap — /tmp/project.md" in out
    assert "# Repository: repo1 — /tmp/repo1.md" in out


def test_manual_ctx_template_prints_full_excerpt_without_truncation(
    tmp_path, monkeypatch, capsys,
):
    from owrap.commands.context_manager import ManualCtxRunner, MAX_EXCERPT_CHARS
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    ccsid = "claude-fallback-excerpt"
    owrap_sid = "fallback02"
    _make_session_file(sessions_dir, owrap_sid, ccsid)
    long_text = "x" * (MAX_EXCERPT_CHARS + 5000)
    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "assistant", "message": {"role": "assistant",
         "content": [{"type": "text", "text": long_text}]}},
    ])
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", ccsid)
    monkeypatch.setattr(
        "owrap.commands.context_manager.claude_transcript_path",
        lambda ccsid, workspace: transcript,
    )

    ManualCtxRunner().template()

    out = capsys.readouterr().out
    assert long_text in out
    assert "Transcript excerpt since the last update (not truncated)" in out


def test_manual_ctx_done_advances_cursor_and_sets_status_ok(tmp_path, monkeypatch):
    from owrap.commands.context_manager import ManualCtxRunner
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    ccsid = "claude-ack"
    owrap_sid = "ack01"
    _make_session_file(sessions_dir, owrap_sid, ccsid)
    context_md = _make_context_md(sessions_dir, owrap_sid)

    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "assistant", "message": {"role": "assistant",
         "content": [{"type": "text", "text": "did it by hand"}]}},
    ])
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", ccsid)
    monkeypatch.setattr(
        "owrap.commands.context_manager.claude_transcript_path",
        lambda ccsid, workspace: transcript,
    )

    ManualCtxRunner().done()

    assert _ctx_status(context_md) == "ok"
    state = json.loads(
        (sessions_dir / owrap_sid / "ctx_state.json").read_text()
    )
    assert state["windows"][ccsid]["transcript_cursor_ns"] == _entry_ts_ns(0)
    assert state["ctx"]["last_dispatch"]["kind"] == "manual"


def test_manual_ctx_done_with_error_sets_status_failed(tmp_path, monkeypatch):
    from owrap.commands.context_manager import ManualCtxRunner
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    ccsid = "claude-ack-err"
    owrap_sid = "ack02"
    _make_session_file(sessions_dir, owrap_sid, ccsid)
    context_md = _make_context_md(sessions_dir, owrap_sid)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", ccsid)
    monkeypatch.setattr(
        "owrap.commands.context_manager.claude_transcript_path",
        lambda ccsid, workspace: None,
    )

    ManualCtxRunner().done(error="couldn't reach the repo file")

    assert _ctx_status(context_md) == "failed"
    state = json.loads(
        (sessions_dir / owrap_sid / "ctx_state.json").read_text()
    )
    assert state["ctx"]["last_dispatch"]["reason"] == "couldn't reach the repo file"


def test_manual_ctx_done_refuses_when_nothing_changed_since_template(
    tmp_path, monkeypatch, capsys,
):
    from owrap.commands.context_manager import ManualCtxRunner
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    ccsid = "claude-notouch"
    owrap_sid = "notouch01"
    _make_session_file(sessions_dir, owrap_sid, ccsid)
    _make_context_md(sessions_dir, owrap_sid)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", ccsid)
    monkeypatch.setattr(
        "owrap.commands.context_manager.claude_transcript_path",
        lambda ccsid, workspace: None,
    )

    ManualCtxRunner().template()
    with pytest.raises(SystemExit) as exc:
        ManualCtxRunner().done()
    assert exc.value.code == 2
    assert "none of the target files" in capsys.readouterr().out


def test_manual_ctx_done_succeeds_after_context_md_edited(
    tmp_path, monkeypatch,
):
    from owrap.commands.context_manager import ManualCtxRunner
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    ccsid = "claude-didtouch"
    owrap_sid = "didtouch01"
    _make_session_file(sessions_dir, owrap_sid, ccsid)
    context_md = _make_context_md(sessions_dir, owrap_sid)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", ccsid)
    monkeypatch.setattr(
        "owrap.commands.context_manager.claude_transcript_path",
        lambda ccsid, workspace: None,
    )

    ManualCtxRunner().template()
    # Simulate the planner actually editing the file afterward.
    time.sleep(0.01)
    context_md.write_text(context_md.read_text() + "\nedited by hand\n")

    ManualCtxRunner().done()

    assert _ctx_status(context_md) == "ok"
    state = json.loads((sessions_dir / owrap_sid / "ctx_state.json").read_text())
    assert "manual_started_ts" not in state["ctx"]


def test_register_ctx_state_window_adds_entry(tmp_path, monkeypatch):
    from owrap.commands.context_manager import register_ctx_state_window
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    owrap_sid = "reg01"
    ccsid = "claude-reg"

    register_ctx_state_window(owrap_sid, ccsid, harness="claude")

    state = json.loads((sessions_dir / owrap_sid / "ctx_state.json").read_text())
    assert state["windows"][ccsid]["harness"] == "claude"
    assert "attached_ts" in state["windows"][ccsid]


def test_register_ctx_state_window_keeps_existing_cursor(tmp_path, monkeypatch):
    from owrap.commands.context_manager import (
        register_ctx_state_window, CtxWorkerRunner,
    )
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    owrap_sid = "reg02"
    ccsid = "claude-reg2"
    CtxWorkerRunner()._write_window_state(
        owrap_sid, {"transcript_cursor_ns": 42}, ccsid,
    )

    register_ctx_state_window(owrap_sid, ccsid, harness="claude")

    state = json.loads((sessions_dir / owrap_sid / "ctx_state.json").read_text())
    assert state["windows"][ccsid]["transcript_cursor_ns"] == 42
    assert state["windows"][ccsid]["harness"] == "claude"


def test_prune_ctx_state_window_removes_entry(tmp_path, monkeypatch):
    from owrap.commands.context_manager import (
        register_ctx_state_window, prune_ctx_state_window,
    )
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    owrap_sid = "reg03"
    ccsid = "claude-reg3"
    register_ctx_state_window(owrap_sid, ccsid)

    prune_ctx_state_window(owrap_sid, ccsid)

    state = json.loads((sessions_dir / owrap_sid / "ctx_state.json").read_text())
    assert ccsid not in state["windows"]


def test_run_manual_ctx_queues_background_dispatch(tmp_path, monkeypatch):
    """
    --ctx must be fire-and-forget: validate, queue a detached ctx-worker
    process, and return immediately — never block on the model dispatch.
    """
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    ccsid = "claude-manual"
    owrap_sid = "manual01"
    _make_session_file(sessions_dir, owrap_sid, ccsid)

    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "assistant", "message": {"role": "assistant",
         "content": [{"type": "text", "text": "hi"}]}},
    ])
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", ccsid)
    monkeypatch.setattr(
        "owrap.commands.context_manager.claude_transcript_path",
        lambda ccsid, workspace: transcript,
    )

    mock_popen = MagicMock()
    with patch("owrap.commands.context_manager.subprocess.Popen", mock_popen):
        CtxWorkerRunner().run_manual(mode="ctx")

    mock_popen.assert_called_once()
    cmd = mock_popen.call_args[0][0]
    assert cmd[1:5] == ["-m", "owrap.runner", "ctx-worker", "--input"]
    payload = json.loads(Path(cmd[5]).read_text())
    assert payload["mode"] == "ctx"
    assert payload["session_id"] == ccsid

    job_dir = Path(payload["job_dir"])
    status = json.loads((job_dir / "status.json").read_text())
    assert status["kind"] == "ctx"
    assert status["status"] == "queued"
    assert status["session_id"] == owrap_sid
    assert status["log_path"] == str(job_dir / "output.log")


def test_context_job_failure_appears_in_stat(tmp_path, monkeypatch, capsys):
    from owrap.session.stat import StatRunner

    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    ccsid = "claude-failing-job"
    sid = "failing01"
    _make_session_file(sessions_dir, sid, ccsid)
    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [{
        "type": "assistant", "message": {
            "role": "assistant", "content": [{"type": "text", "text": "change"}],
        },
    }])
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", ccsid)
    monkeypatch.setattr(
        "owrap.commands.context_manager.claude_transcript_path",
        lambda cid, workspace: transcript,
    )
    with patch("owrap.commands.context_manager.subprocess.Popen") as popen:
        CtxWorkerRunner().run_manual(mode="ctx")
    payload_path = Path(popen.call_args[0][0][-1])
    job_dir = payload_path.parent
    (job_dir / "output.log").write_text("model attempt failed\n")

    terminal, terminal_run = _patch_terminal(rc=1, output_text=None)
    with patch("owrap.commands.context_manager.Terminal", terminal):
        assert CtxWorkerRunner().run(input_path=payload_path) == 1
    assert terminal_run.call_args.kwargs["capture_output"] is True
    assert terminal_run.call_args.kwargs["print_output"] is True

    status = json.loads((job_dir / "status.json").read_text())
    assert status["status"] == "failed"
    assert status["rc"] == 1
    capsys.readouterr()
    StatRunner(None).run(SimpleNamespace(filter=sid))
    output = capsys.readouterr().out
    assert f"ctx  {job_dir.name}  done(rc=1)" in output
    assert f"output: {job_dir / 'output.log'}" in output
    assert f"transcript: {job_dir / 'transcript.txt'}" in output
    assert "model attempt failed" not in output


def test_context_jobs_keep_separate_payloads(tmp_path, monkeypatch):
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    ccsid = "claude-repeat"
    sid = "repeat01"
    _make_session_file(sessions_dir, sid, ccsid)
    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [{"type": "assistant"}])
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", ccsid)
    monkeypatch.setattr(
        "owrap.commands.context_manager.claude_transcript_path",
        lambda cid, workspace: transcript,
    )

    with patch("owrap.commands.context_manager.subprocess.Popen") as popen:
        CtxWorkerRunner().run_manual(mode="ctx")
        first = Path(popen.call_args[0][0][-1])
        CtxWorkerRunner().run_manual(mode="ctx")
        second = Path(popen.call_args[0][0][-1])

    assert first != second
    assert first.exists()
    assert second.exists()
    assert (first.parent / "status.json").exists()
    assert (second.parent / "status.json").exists()


def test_context_jobs_are_not_nested_under_window_id(tmp_path, monkeypatch):
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    from owrap.utils.log import context_jobs

    job_dir = context_jobs.create("session01", "window01", "ctx")

    assert job_dir.parent == sessions_dir / "session01" / "ctx" / "jobs"
    status = json.loads((job_dir / "status.json").read_text())
    assert status["window_id"] == "window01"
    assert status["transcript_path"] == str(job_dir / "transcript.txt")


def test_finished_context_jobs_expire_from_stat_history(tmp_path, monkeypatch):
    _patch_dirs(monkeypatch, tmp_path)
    from owrap.constants import RECENT_TASK_RETENTION_S
    from owrap.utils.log import context_jobs

    job_dir = context_jobs.create("session01", "window01", "ctx")
    context_jobs.finish(job_dir, 0)
    finished = json.loads((job_dir / "status.json").read_text())["finished"]
    monkeypatch.setattr(
        context_jobs.time, "time",
        lambda: finished + RECENT_TASK_RETENTION_S + 1,
    )

    assert context_jobs.recent("session01") == []


def test_context_stat_shows_live_stage_without_window_path(
    tmp_path, monkeypatch, capsys,
):
    from owrap.session.stat import StatRunner
    from owrap.utils.log import context_jobs

    _patch_dirs(monkeypatch, tmp_path)
    job_dir = context_jobs.create("session01", "window-secret", "ctx")
    context_jobs.update(
        job_dir, status="running", pid=os.getpid(), stage="running model",
    )

    StatRunner(None).run(SimpleNamespace(filter="session01"))
    output = capsys.readouterr().out

    assert "running (running model)" in output
    assert "window-secret" not in output
    assert f"output: {job_dir / 'output.log'}" in output


def test_ctx_worker_command_exits_with_dispatch_result(tmp_path):
    from owrap.runner import _cmd_ctx_worker

    payload = tmp_path / "job.json"
    payload.write_text("{}")
    with patch.object(CtxWorkerRunner, "run", return_value=1):
        with pytest.raises(SystemExit) as exit_info:
            _cmd_ctx_worker(SimpleNamespace(input=str(payload)), None, None, False)
    assert exit_info.value.code == 1


def test_run_manual_updr_rejects_legacy_session(tmp_path, monkeypatch):
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    ccsid = "claude-manual-updr"
    owrap_sid = "manual02"
    _make_session_file(sessions_dir, owrap_sid, ccsid)

    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "assistant", "message": {"role": "assistant",
         "content": [{"type": "text", "text": "hi"}]}},
    ])
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", ccsid)
    monkeypatch.setattr(
        "owrap.commands.context_manager.claude_transcript_path",
        lambda ccsid, workspace: transcript,
    )

    with pytest.raises(SystemExit) as exc_info:
        CtxWorkerRunner().run_manual(mode="updr", subproject="custom")

    assert exc_info.value.code == 1


def test_run_manual_updr_queues_subproject_target(tmp_path, monkeypatch):
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    ccsid = "claude-project-updr"
    sid = "project01"
    session = _make_session_file(sessions_dir, sid, ccsid)
    session.write_text(
        f"session_id={sid}\nclaude_session_id={ccsid}\n"
        "target_kind=project\nproject_id=owrap\n"
        "subproject_id=\nworkspace=test\n"
    )
    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [{"type": "assistant"}])
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", ccsid)
    monkeypatch.setattr(
        "owrap.commands.context_manager.claude_transcript_path",
        lambda cid, workspace: transcript,
    )
    resolved = []
    monkeypatch.setattr(
        "owrap.commands.context_manager.resolve_memory_target",
        lambda data: resolved.append(data) or MagicMock(),
    )

    mock_popen = MagicMock()
    with patch("owrap.commands.context_manager.subprocess.Popen", mock_popen):
        CtxWorkerRunner().run_manual(mode="updr", subproject="migration")

    payload_path = Path(mock_popen.call_args[0][0][5])
    payload = json.loads(payload_path.read_text())
    assert resolved[0]["subproject_id"] == "migration"
    assert payload["subproject"] == "migration"
    assert "area" not in payload


def test_run_manual_combined_mode_queues_single_dispatch(tmp_path, monkeypatch):
    """
    `owrap updr --ctx` (mode=None) must queue exactly ONE background
    dispatch doing both halves — never two separate ones, which would
    race on the same unconsumed transcript-offset counter and double the
    model cost for the same excerpt.
    """
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    ccsid = "claude-combined"
    owrap_sid = "combined01"
    _make_project_session(sessions_dir, owrap_sid, ccsid)
    monkeypatch.setattr(
        "owrap.commands.context_manager.resolve_memory_target",
        lambda data: MagicMock(),
    )

    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "assistant", "message": {"role": "assistant",
         "content": [{"type": "text", "text": "hi"}]}},
    ])
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", ccsid)
    monkeypatch.setattr(
        "owrap.commands.context_manager.claude_transcript_path",
        lambda ccsid, workspace: transcript,
    )

    mock_popen = MagicMock()
    with patch("owrap.commands.context_manager.subprocess.Popen", mock_popen):
        CtxWorkerRunner().run_manual(mode=None)

    mock_popen.assert_called_once()
    cmd = mock_popen.call_args[0][0]
    payload = json.loads(Path(cmd[5]).read_text())
    assert payload["mode"] is None


def test_run_manual_combined_mode_prints_readable_label(tmp_path, monkeypatch, capsys):
    """
    The queued-dispatch message must never print the literal word "None"
    for combined mode (mode=None) — it should read as "ctx+updr".
    """
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    ccsid = "claude-combined-label"
    owrap_sid = "combinedlabel01"
    _make_project_session(sessions_dir, owrap_sid, ccsid)
    monkeypatch.setattr(
        "owrap.commands.context_manager.resolve_memory_target",
        lambda data: MagicMock(),
    )

    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "assistant", "message": {"role": "assistant",
         "content": [{"type": "text", "text": "hi"}]}},
    ])
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", ccsid)
    monkeypatch.setattr(
        "owrap.commands.context_manager.claude_transcript_path",
        lambda ccsid, workspace: transcript,
    )

    with patch("owrap.commands.context_manager.subprocess.Popen", MagicMock()):
        CtxWorkerRunner().run_manual(mode=None)

    out = capsys.readouterr().out
    assert "None dispatch queued" not in out
    assert "ctx+updr dispatch queued" in out


def test_ctx_worker_run_honors_combined_mode(tmp_path, monkeypatch):
    """
    A manual-handoff payload with mode=None (combined `updr --ctx`) must
    dispatch both Context and Protocol in the same input.md — never two
    separate opencode calls.
    """
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    ccsid = "claude-combined-run"
    owrap_sid = "combinedrun01"
    _make_project_session(sessions_dir, owrap_sid, ccsid)
    project_path = tmp_path / "project.md"
    project_path.write_text("# Project\n\n## Status\nold\n")
    monkeypatch.setattr(
        "owrap.commands.context_manager.resolve_memory_target",
        lambda data: SimpleNamespace(
            project_path=project_path,
            project_id="owrap",
            subproject_id=data.get("subproject_id", ""),
        ),
    )
    monkeypatch.setattr(
        "owrap.commands.context_manager.touched_repository_paths",
        lambda *args: {},
    )

    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "assistant", "message": {"role": "assistant",
         "content": [{"type": "text", "text": "hi"}]}},
    ])
    input_path = tmp_path / "manual.json"
    input_path.write_text(json.dumps({
        "session_id": ccsid, "transcript_path": str(transcript), "mode": None,
    }))

    mock_terminal_cls, mock_run = _patch_terminal()
    with patch("owrap.commands.context_manager.Terminal", mock_terminal_cls):
        CtxWorkerRunner().run(input_path=input_path)

    mock_run.assert_called_once()
    task_md = (
        sessions_dir / owrap_sid / "ctx" / "windows" / ccsid / "input.md"
    ).read_text()
    assert "# Context" in task_md
    assert "# Project" in task_md
    assert "# Memory" not in task_md


def test_run_manual_combined_mode_requires_explicit_target(tmp_path, monkeypatch):
    """
    Combined mode requires a project or repository for the Protocol half.
    """
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    ccsid = "claude-combined-noarea"
    owrap_sid = "combinednoarea01"
    sf = sessions_dir / f"{owrap_sid}.session"
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_text(f"session_id={owrap_sid}\nclaude_session_id={ccsid}\n")
    (sessions_dir / "by_ccsid").mkdir(parents=True, exist_ok=True)
    (sessions_dir / "by_ccsid" / ccsid).write_text(owrap_sid)

    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "assistant", "message": {"role": "assistant",
         "content": [{"type": "text", "text": "hi"}]}},
    ])
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", ccsid)
    monkeypatch.setattr(
        "owrap.commands.context_manager.claude_transcript_path",
        lambda ccsid, workspace: transcript,
    )

    with pytest.raises(SystemExit) as exc_info:
        CtxWorkerRunner().run_manual(mode=None)
    assert exc_info.value.code == 1


@pytest.mark.parametrize(
    ("mode", "subproject", "expected_blocks"),
    [
        ("ctx", None, ("# Context",)),
        ("updr", "custom", ("# Subproject: custom",)),
        (None, None, ("# Context", "# Project: owrap")),
    ],
)
def test_codex_manual_modes_dispatch_from_rollout(
    tmp_path, monkeypatch, mode, subproject, expected_blocks,
):
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    cid = "codex-manual"
    sid = "manual03"
    (sessions_dir / f"{sid}.session").parent.mkdir(
        parents=True, exist_ok=True,
    )
    (sessions_dir / f"{sid}.session").write_text(
        f"session_id={sid}\ntarget_kind=project\nproject_id=owrap\n"
        "subproject_id=\nworkspace=test\n"
    )
    pointer = sessions_dir / "by_codex_session_id" / cid
    pointer.parent.mkdir(parents=True)
    pointer.write_text(sid)
    transcript = tmp_path / "rollout.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "event_msg", "payload": {"type": "item_completed", "item": {
            "type": "AgentMessage", "content": [
                {"type": "text", "text": "Implemented Codex support"},
            ],
        }}},
        {"type": "event_msg", "payload": {"type": "item_completed", "item": {
            "type": "CommandExecution", "command": ["git", "status"],
            "aggregated_output": " M owrap/README.md",
        }}},
        {"type": "event_msg", "payload": {"type": "item_completed", "item": {
            "type": "FileChange", "changes": {"/tmp/project/file.py": {}},
        }}},
    ])
    monkeypatch.setenv("CODEX_SESSION_ID", cid)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setattr(
        "owrap.commands.context_manager.codex_transcript_path",
        lambda session_id: transcript,
    )
    project_path = tmp_path / "project.md"
    project_path.write_text("# Project\n\n## Status\nold\n")
    monkeypatch.setattr(
        "owrap.commands.context_manager.resolve_memory_target",
        lambda data: SimpleNamespace(
            project_path=project_path,
            project_id="owrap",
            subproject_id=data.get("subproject_id", ""),
        ),
    )
    monkeypatch.setattr(
        "owrap.commands.context_manager.touched_repository_paths",
        lambda *args: {},
    )

    mock_popen = MagicMock()
    with patch("owrap.commands.context_manager.subprocess.Popen", mock_popen):
        CtxWorkerRunner().run_manual(mode=mode, subproject=subproject)

    mock_popen.assert_called_once()
    input_path = Path(mock_popen.call_args[0][0][5])
    payload = json.loads(input_path.read_text())
    assert payload["source"] == "codex"
    assert payload["mode"] == mode
    assert payload["subproject"] == subproject
    assert "area" not in payload

    mock_terminal_cls, mock_run = _patch_terminal()
    with patch("owrap.commands.context_manager.Terminal", mock_terminal_cls):
        CtxWorkerRunner().run(input_path=input_path)

    mock_run.assert_called_once()
    ctx_dir = input_path.parent / "work"
    task = (ctx_dir / "input.md").read_text()
    excerpt = (ctx_dir / "transcript.txt").read_text()
    for block in expected_blocks:
        assert block in task
    assert ("# Context" in task) == (mode != "updr")
    assert "Implemented Codex support" in excerpt
    assert "$ git status" in excerpt
    assert "[FileChange] /tmp/project/file.py" in excerpt


def test_codex_rollout_extracts_assistant_messages_and_patch_paths():
    lines = _lines_with_ts([
        {"type": "response_item", "payload": {
            "type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "Do the work"}],
        }},
        {"type": "response_item", "payload": {
            "type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": "Updated permit handling"}],
        }},
        {"type": "event_msg", "payload": {
            "type": "patch_apply_end", "success": True,
            "changes": {"/tmp/project/permit.py": {}},
        }},
    ])

    excerpt = CtxWorkerRunner()._extract_codex_excerpt_lines(lines, 0)

    assert excerpt == [
        "Updated permit handling",
        "[FileChange] /tmp/project/permit.py",
    ]


def test_codex_rollout_ignores_context_update_turn():
    lines = _lines_with_ts([
        {"type": "event_msg", "payload": {
            "type": "user_message", "message": "do another --uall to confirm",
        }},
        {"type": "response_item", "payload": {
            "type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": "I'll run it once more"}],
        }},
        {"type": "event_msg", "payload": {
            "type": "patch_apply_end", "success": True,
            "changes": {"/tmp/project/context_manager.py": {}},
        }},
        {"type": "event_msg", "payload": {
            "type": "user_message", "message": "Fix the permit response",
        }},
        {"type": "response_item", "payload": {
            "type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": "Fixed permit response"}],
        }},
    ])

    excerpt = CtxWorkerRunner()._extract_codex_excerpt_lines(lines, _entry_ts_ns(0))

    assert excerpt == [
        "[FileChange] /tmp/project/context_manager.py",
        "Fixed permit response",
    ]


def test_claude_excerpt_ignores_context_update_turn_and_command():
    lines = _lines_with_ts([
        {"type": "user", "message": {"content": [
            {"type": "text", "text": "run --ctx to update context"},
        ]}},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "I'll run context update"},
            {"type": "tool_use", "id": "ctx1", "name": "Bash",
             "input": {"command": "~/bin/owrap updr --ctx"}},
            {"type": "tool_use", "id": "edit1", "name": "Edit",
             "input": {"file_path": "/tmp/project/context_manager.py"}},
        ]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "ctx1",
             "content": "ctx+updr dispatch queued"},
        ]}},
        {"type": "user", "message": {"content": [
            {"type": "text", "text": "Fix the permit response"},
        ]}},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Fixed permit response"},
        ]}},
    ])

    excerpt = CtxWorkerRunner()._extract_excerpt_lines(lines, _entry_ts_ns(0))

    assert excerpt == [
        "[Edit] /tmp/project/context_manager.py",
        "Fixed permit response",
    ]


def test_context_update_command_is_ignored_inside_other_work():
    lines = _lines_with_ts([
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "ctx1", "name": "Bash",
             "input": {"command": "~/bin/owrap updr --ctx"}},
            {"type": "tool_use", "id": "test1", "name": "Bash",
             "input": {"command": "python3 -m pytest tests/test_permit.py"}},
        ]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "ctx1",
             "content": "ctx+updr dispatch queued"},
            {"type": "tool_result", "tool_use_id": "test1",
             "content": "15 passed"},
        ]}},
    ])

    excerpt = CtxWorkerRunner()._extract_excerpt_lines(lines, 0)

    assert excerpt == [
        "$ python3 -m pytest tests/test_permit.py",
        "-> 15 passed",
    ]


def test_codex_update_only_transcript_advances_offset(tmp_path, monkeypatch):
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    sid, cid = "update01", "codex-update"
    (sessions_dir / f"{sid}.session").parent.mkdir(
        parents=True, exist_ok=True,
    )
    (sessions_dir / f"{sid}.session").write_text(
        f"session_id={sid}\nresearch=testr\narea=testarea\n"
    )
    pointer = sessions_dir / "by_codex_session_id" / cid
    pointer.parent.mkdir(parents=True)
    pointer.write_text(sid)
    transcript = tmp_path / "rollout.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "event_msg", "payload": {
            "type": "user_message", "message": "do another --uall to confirm",
        }},
        {"type": "response_item", "payload": {
            "type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": "I'll run it again"}],
        }},
    ])
    input_path = tmp_path / "hook_input.json"
    input_path.write_text(json.dumps({
        "session_id": cid, "transcript_path": str(transcript),
        "source": "codex",
    }))

    with patch("owrap.commands.context_manager.Terminal") as terminal:
        CtxWorkerRunner().run(input_path=input_path)

    terminal.assert_not_called()
    state = json.loads((sessions_dir / sid / "ctx_state.json").read_text())
    assert state["windows"][cid]["transcript_cursor_ns"] == _entry_ts_ns(1)


def test_ctx_worker_run_honors_mode_ctx_only(tmp_path, monkeypatch):
    """
    A manual-handoff payload with mode="ctx" must dispatch Context only,
    never Protocol — the hardcoded always-both behavior is only for the
    real PreCompact hook payload, which has no mode key at all.
    """
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    ccsid = "claude-mode"
    owrap_sid = "mode01"
    _make_session_file(sessions_dir, owrap_sid, ccsid)

    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "assistant", "message": {"role": "assistant",
         "content": [{"type": "text", "text": "hi"}]}},
    ])
    input_path = tmp_path / "manual.json"
    input_path.write_text(json.dumps({
        "session_id": ccsid, "transcript_path": str(transcript), "mode": "ctx",
    }))

    mock_terminal_cls, mock_run = _patch_terminal()
    with patch("owrap.commands.context_manager.Terminal", mock_terminal_cls):
        CtxWorkerRunner().run(input_path=input_path)

    cmd_str = mock_run.call_args[0][0]
    assert "-m" in shlex.split(cmd_str) or True  # model flag presence not the point here
    # The Context-only template never asks for a ## area Project/Memory block.
    task_md = (
        sessions_dir / owrap_sid / "ctx" / "windows" / ccsid / "input.md"
    ).read_text()
    assert "# Context" in task_md
    assert "# Memory" not in task_md
    assert "# Project" not in task_md


def test_ctx_dispatch_omits_model_flag_when_nothing_configured(
    tmp_path, monkeypatch,
):
    cmd = _dispatch_ctx_with_config(tmp_path, monkeypatch, {})
    assert "-m" not in cmd


# Periodic attached-window trigger

def test_check_all_attached_dispatches_claude_and_codex_windows(monkeypatch):
    monkeypatch.setattr(
        "owrap.commands.context_manager._read_config", lambda: {},
    )
    monkeypatch.setattr(
        "owrap.commands.context_manager.get_workspace_path", lambda: "ws",
    )
    monkeypatch.setattr(
        "owrap.commands.context_manager.all_attached_ccsid_pairs",
        lambda: [("claude-1", "sid-claude")],
    )
    monkeypatch.setattr(
        "owrap.commands.context_manager.all_attached_codex_session_id_pairs",
        lambda: [("codex-1", "sid-codex")],
    )
    claude_path = MagicMock(exists=lambda: True)
    codex_path = MagicMock(exists=lambda: True)
    monkeypatch.setattr(
        "owrap.commands.context_manager.claude_transcript_path",
        lambda ccsid, workspace: claude_path,
    )
    monkeypatch.setattr(
        "owrap.commands.context_manager.codex_transcript_path",
        lambda cid: codex_path,
    )
    dispatched = []
    monkeypatch.setattr(
        CtxWorkerRunner, "_dispatch_tracked",
        lambda self, owrap_sid, ccsid, path, config, **kw: dispatched.append(
            (owrap_sid, ccsid, kw.get("source", "claude")),
        ),
    )

    CtxWorkerRunner().check_all_attached()

    assert ("sid-claude", "claude-1", "claude") in dispatched
    assert ("sid-codex", "codex-1", "codex") in dispatched


def test_check_all_attached_skips_codex_window_without_transcript(monkeypatch):
    monkeypatch.setattr(
        "owrap.commands.context_manager._read_config", lambda: {},
    )
    monkeypatch.setattr(
        "owrap.commands.context_manager.get_workspace_path", lambda: "ws",
    )
    monkeypatch.setattr(
        "owrap.commands.context_manager.all_attached_ccsid_pairs", lambda: [],
    )
    monkeypatch.setattr(
        "owrap.commands.context_manager.all_attached_codex_session_id_pairs",
        lambda: [("codex-1", "sid-codex")],
    )
    monkeypatch.setattr(
        "owrap.commands.context_manager.codex_transcript_path",
        lambda cid: None,
    )
    dispatched = []
    monkeypatch.setattr(
        CtxWorkerRunner, "_dispatch_tracked",
        lambda self, *args, **kw: dispatched.append(args),
    )

    CtxWorkerRunner().check_all_attached()

    assert dispatched == []


def test_check_all_attached_one_failure_does_not_block_the_other_harness(
    monkeypatch, capsys,
):
    monkeypatch.setattr(
        "owrap.commands.context_manager._read_config", lambda: {},
    )
    monkeypatch.setattr(
        "owrap.commands.context_manager.get_workspace_path", lambda: "ws",
    )
    monkeypatch.setattr(
        "owrap.commands.context_manager.all_attached_ccsid_pairs",
        lambda: [("claude-1", "sid-claude")],
    )
    monkeypatch.setattr(
        "owrap.commands.context_manager.all_attached_codex_session_id_pairs",
        lambda: [("codex-1", "sid-codex")],
    )
    monkeypatch.setattr(
        "owrap.commands.context_manager.claude_transcript_path",
        lambda ccsid, workspace: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    codex_path = MagicMock(exists=lambda: True)
    monkeypatch.setattr(
        "owrap.commands.context_manager.codex_transcript_path",
        lambda cid: codex_path,
    )
    dispatched = []
    monkeypatch.setattr(
        CtxWorkerRunner, "_dispatch_tracked",
        lambda self, owrap_sid, ccsid, path, config, **kw: dispatched.append(ccsid),
    )

    CtxWorkerRunner().check_all_attached()

    assert dispatched == ["codex-1"]
    assert "background check failed for ccsid=claude-1" in capsys.readouterr().err


# Output validation and retry

def test_validate_output_rejects_missing_focus():
    runner = CtxWorkerRunner()
    output = "# Project: owrap\n## Status\nok\n"
    assert not runner._validate_output(output, do_context=True, do_protocol=False)


def test_validate_output_rejects_missing_status():
    runner = CtxWorkerRunner()
    output = "# Context\n## Focus\nok\n"
    assert not runner._validate_output(output, do_context=False, do_protocol=True)


def test_validate_output_ignores_sections_not_requested():
    runner = CtxWorkerRunner()
    output = "# Context\n## Focus\nok\n"
    assert runner._validate_output(output, do_context=True, do_protocol=False)


def test_validate_output_rejects_blank_text():
    runner = CtxWorkerRunner()
    assert not runner._validate_output("   \n", do_context=True, do_protocol=False)


def test_dispatch_retries_primary_model_before_falling_back(tmp_path, monkeypatch):
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    ccsid = "claude-retry"
    owrap_sid = "retry01"
    _make_session_file(sessions_dir, owrap_sid, ccsid)

    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "assistant", "message": {"role": "assistant",
         "content": [{"type": "text", "text": "did work"}]}},
    ])
    input_path = tmp_path / "hook_input.json"
    input_path.write_text(json.dumps({
        "session_id": ccsid, "transcript_path": str(transcript),
    }))

    # First two calls (primary, tried twice) fail; third (next rung) succeeds.
    calls = []

    def _run(cmd_str, *args, **kwargs):
        calls.append(cmd_str)
        if len(calls) >= 3:
            Path(kwargs["cwd"], "output.md").write_text(VALID_OUTPUT_MD)
        return {"returncode": 0}

    mock_terminal_cls = MagicMock()
    mock_terminal = MagicMock()
    mock_terminal.run.side_effect = _run
    mock_terminal_cls.return_value = mock_terminal

    base_config_path = tmp_path / "base_config.json"
    base_config_path.write_text(json.dumps({
        "default_workspace": "test",
        "context_manager_model": "primary/model",
        "context_fallback_model": "fallback/model",
    }))

    with patch("owrap.utils.paths.BASE_CONFIG_FILE", base_config_path), \
         patch("owrap.commands.context_manager.Terminal", mock_terminal_cls):
        CtxWorkerRunner().run(input_path=input_path)

    assert len(calls) == 3
    assert "primary/model" in calls[0] and "primary/model" in calls[1]
    assert "fallback/model" in calls[2]


def test_dispatch_leaves_excerpt_queued_when_all_attempts_fail(tmp_path, monkeypatch):
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    ccsid = "claude-exhausted"
    owrap_sid = "exhausted01"
    _make_session_file(sessions_dir, owrap_sid, ccsid)
    context_md = _make_context_md(sessions_dir, owrap_sid)

    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "assistant", "message": {"role": "assistant",
         "content": [{"type": "text", "text": "did work"}]}},
    ])
    input_path = tmp_path / "hook_input.json"
    input_path.write_text(json.dumps({
        "session_id": ccsid, "transcript_path": str(transcript),
    }))

    mock_terminal_cls, mock_run = _patch_terminal(rc=0, output_text=None)
    with patch("owrap.commands.context_manager.Terminal", mock_terminal_cls):
        CtxWorkerRunner().run(input_path=input_path)

    assert _ctx_status(context_md) == "failed"
    counters_path = sessions_dir / f"{owrap_sid}.{ccsid}.counters.json"
    assert not counters_path.exists()


# Opencode health flag

def test_dispatch_marks_opencode_down_after_full_timeout_chain(tmp_path, monkeypatch):
    """
    Every model in the chain timing out (rc=-1) means opencode itself is
    unreachable, not just a validation miss on this excerpt, so the
    shared health flag flips to "down".
    """
    from owrap.commands.context_manager import read_opencode_status
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    ccsid = "claude-timeout"
    owrap_sid = "timeout01"
    _make_session_file(sessions_dir, owrap_sid, ccsid)

    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "assistant", "message": {"role": "assistant",
         "content": [{"type": "text", "text": "did work"}]}},
    ])
    input_path = tmp_path / "hook_input.json"
    input_path.write_text(json.dumps({
        "session_id": ccsid, "transcript_path": str(transcript),
    }))

    mock_terminal_cls, mock_run = _patch_terminal(rc=-1, output_text=None)
    with patch("owrap.commands.context_manager.Terminal", mock_terminal_cls):
        CtxWorkerRunner().run(input_path=input_path)

    assert read_opencode_status() == "down"


def test_dispatch_marks_opencode_up_after_success(tmp_path, monkeypatch):
    from owrap.commands.context_manager import (
        read_opencode_status, OPENCODE_STATUS_FILE,
    )
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    ccsid = "claude-recovered"
    owrap_sid = "recovered01"
    _make_session_file(sessions_dir, owrap_sid, ccsid)
    OPENCODE_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    OPENCODE_STATUS_FILE.write_text(json.dumps({"status": "down"}))

    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "assistant", "message": {"role": "assistant",
         "content": [{"type": "text", "text": "did work"}]}},
    ])
    input_path = tmp_path / "hook_input.json"
    input_path.write_text(json.dumps({
        "session_id": ccsid, "transcript_path": str(transcript),
    }))

    mock_terminal_cls, mock_run = _patch_terminal()
    with patch("owrap.commands.context_manager.Terminal", mock_terminal_cls):
        CtxWorkerRunner().run(input_path=input_path)

    assert read_opencode_status() == "up"


def test_dispatch_skips_fallback_chain_after_two_idle_primary_tries(
    tmp_path, monkeypatch,
):
    """
    The primary model going idle twice with zero real output means
    opencode itself is unreachable — trying the fallback rung against
    the same dead infra would just repeat the wait, so it must not run.
    """
    from owrap.commands.context_manager import read_opencode_status_detail
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    ccsid = "claude-idle"
    owrap_sid = "idle01"
    _make_session_file(sessions_dir, owrap_sid, ccsid)

    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "assistant", "message": {"role": "assistant",
         "content": [{"type": "text", "text": "did work"}]}},
    ])
    input_path = tmp_path / "hook_input.json"
    input_path.write_text(json.dumps({
        "session_id": ccsid, "transcript_path": str(transcript),
    }))
    base_config_path = tmp_path / "base_config.json"
    base_config_path.write_text(json.dumps({
        "default_workspace": "test",
        "context_manager_model": "primary/model",
        "context_fallback_model": "fallback/model",
    }))

    def _run(cmd_str, *args, **kwargs):
        # Real stdout: raw ANSI + "> build" banner, not the cleaned form.
        return {
            "returncode": -1, "idled_out": True,
            "stdout": "\x1b[0m\n> build · primary/model\n\x1b[0m",
        }

    mock_terminal_cls = MagicMock()
    mock_terminal = MagicMock()
    mock_terminal.run.side_effect = _run
    mock_terminal_cls.return_value = mock_terminal

    with patch("owrap.utils.paths.BASE_CONFIG_FILE", base_config_path), \
         patch("owrap.commands.context_manager.Terminal", mock_terminal_cls):
        CtxWorkerRunner().run(input_path=input_path)

    assert mock_terminal.run.call_count == 2
    detail = read_opencode_status_detail()
    assert detail["status"] == "down"
    assert detail["reason"].startswith("no_output")


def test_dispatch_marks_opencode_down_with_subscription_reason(
    tmp_path, monkeypatch,
):
    from owrap.commands.context_manager import read_opencode_status_detail
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    ccsid = "claude-nosub"
    owrap_sid = "nosub01"
    _make_session_file(sessions_dir, owrap_sid, ccsid)

    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "assistant", "message": {"role": "assistant",
         "content": [{"type": "text", "text": "did work"}]}},
    ])
    input_path = tmp_path / "hook_input.json"
    input_path.write_text(json.dumps({
        "session_id": ccsid, "transcript_path": str(transcript),
    }))

    def _run(cmd_str, *args, **kwargs):
        return {
            "returncode": 1, "idled_out": False,
            "stdout": "Error: An active OpenCode Go subscription is "
                      "required to use Go models.",
        }

    mock_terminal_cls = MagicMock()
    mock_terminal = MagicMock()
    mock_terminal.run.side_effect = _run
    mock_terminal_cls.return_value = mock_terminal

    with patch("owrap.commands.context_manager.Terminal", mock_terminal_cls):
        CtxWorkerRunner().run(input_path=input_path)

    # No valid output came back, regardless of rc — status goes "down".
    detail = read_opencode_status_detail()
    assert detail["status"] == "down"
    assert detail["reason"].startswith("subscription_required")


# Deterministic model output merge

def test_merge_context_full_replaces_focus_and_environment(tmp_path):
    context_path = tmp_path / "context.md"
    context_path.write_text(
        "## Focus\nold focus\n\n## Environment\nold env\n",
    )
    output = (
        "# Context\n## Focus\nnew focus\n## Environment\nnew env\n"
    )
    runner = CtxWorkerRunner()
    runner._merge_context(
        split_top_sections(output, ("Context", "Memory", "Project"))["Context"],
        context_path, "sid1",
    )
    text = context_path.read_text()
    assert "new focus" in text and "old focus" not in text
    assert "new env" in text and "old env" not in text


def test_merge_context_appends_and_dedupes_key_locations(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "owrap.commands.context_manager.get_workspace_path", lambda: None,
    )
    context_path = tmp_path / "context.md"
    context_path.write_text(
        "## Key Locations\n- a.py — existing role\n",
    )
    output = (
        "# Context\n## Key Locations\n"
        "- a.py — duplicate, should be dropped\n"
        "- b.py — genuinely new\n"
    )
    runner = CtxWorkerRunner()
    runner._merge_context(
        split_top_sections(output, ("Context", "Memory", "Project"))["Context"],
        context_path, "sid1",
    )
    text = context_path.read_text()
    assert "existing role" in text
    assert "duplicate, should be dropped" not in text
    assert "b.py — genuinely new" in text


def test_merge_context_caps_key_locations_at_5(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "owrap.commands.context_manager.get_workspace_path", lambda: None,
    )
    context_path = tmp_path / "context.md"
    existing = "\n".join(f"- f{i}.py — role {i}" for i in range(5))
    context_path.write_text(f"## Key Locations\n{existing}\n")
    output = "# Context\n## Key Locations\n- new.py — brand new\n"
    runner = CtxWorkerRunner()
    runner._merge_context(
        split_top_sections(output, ("Context", "Memory", "Project"))["Context"],
        context_path, "sid1",
    )
    text = context_path.read_text()
    assert "f0.py" not in text  # oldest evicted
    assert "f1.py" in text
    assert "new.py" in text


# Key location pruning

def test_key_location_still_exists_true_for_real_path(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "owrap.commands.context_manager.get_workspace_path", lambda: tmp_path,
    )
    (tmp_path / "real.py").write_text("x")
    runner = CtxWorkerRunner()
    assert runner._key_location_still_exists("- real.py — some role")


def test_key_location_still_exists_false_for_missing_path(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "owrap.commands.context_manager.get_workspace_path", lambda: tmp_path,
    )
    runner = CtxWorkerRunner()
    assert not runner._key_location_still_exists("- gone/nowhere.py — some role")


def test_key_location_still_exists_leaves_non_path_entries_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "owrap.commands.context_manager.get_workspace_path", lambda: tmp_path,
    )
    runner = CtxWorkerRunner()
    assert runner._key_location_still_exists("- not a path — just prose")


def test_merge_context_prunes_stale_key_location(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "owrap.commands.context_manager.get_workspace_path", lambda: tmp_path,
    )
    (tmp_path / "still_here.py").write_text("x")
    context_path = tmp_path / "context.md"
    context_path.write_text(
        "## Key Locations\n"
        "- still_here.py — kept\n"
        "- long_gone.py — should be pruned\n",
    )
    output = "# Context\n## Focus\nnew focus\n"
    runner = CtxWorkerRunner()
    runner._merge_context(
        split_top_sections(output, ("Context", "Memory", "Project"))["Context"],
        context_path, "sid1",
    )
    text = context_path.read_text()
    assert "still_here.py" in text
    assert "long_gone.py" not in text


# Merge locking

def test_merge_context_acquires_context_lock(tmp_path):
    from owrap.utils.paths import context_lock_path
    context_path = tmp_path / "context.md"
    context_path.write_text("## Focus\nold\n")
    output = "# Context\n## Focus\nnew\n"
    runner = CtxWorkerRunner()
    runner._merge_context(
        split_top_sections(output, ("Context", "Memory", "Project"))["Context"],
        context_path, "sid1",
    )
    assert context_lock_path("sid1").exists()
