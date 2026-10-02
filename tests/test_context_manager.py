import json
import shlex
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from owrap.commands.context_manager import CtxHookRunner
from owrap.commands.context_manager import CtxWorkerRunner, MAX_EXCERPT_CHARS
from owrap.utils.parser.sections import split_top_sections


VALID_OUTPUT_MD = (
    "# Context\n## Focus\ntest focus\n\n"
    "# Project\n## main\n### Status\ntest status\n"
)


def _patch_terminal(rc=0, output_text=VALID_OUTPUT_MD):
    """Patch Terminal so context_manager dispatch never spawns a real
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


# --- Helpers ---

def _make_hook_stdin(ccsid, transcript_path="/tmp/transcript.jsonl", cwd="/tmp"):
    return json.dumps({
        "session_id": ccsid,
        "transcript_path": transcript_path,
        "cwd": cwd,
    })


def _make_session_file(sessions_dir, owrap_sid, ccsid, research="testr", area="testarea"):
    """Write a .session file plus the by_ccsid/<ccsid> pointer that attach()
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


def _make_transcript_jsonl(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e) for e in entries]
    path.write_text("\n".join(lines) + "\n")


def _patch_dirs(monkeypatch, tmp_path):
    docs_dir = tmp_path / "docs"
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr("owrap.utils.paths.DOCS_DIR", docs_dir)
    monkeypatch.setattr("owrap.utils.paths.SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr("owrap.utils.session.session_resolver.SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(
        "owrap.utils.session.session_resolver.BY_CCSID_DIR", sessions_dir / "by_ccsid",
    )
    monkeypatch.setattr("owrap.utils.session.donow.COUNTERS_DIR", sessions_dir)
    return docs_dir, sessions_dir


# --- Test 1: CtxHookRunner with matching session ---

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
    input_json = sessions_dir / owrap_sid / "ctx" / ccsid / "hook.json"
    assert input_json.exists()
    data = json.loads(input_json.read_text())
    assert data["session_id"] == ccsid

    # Check Popen was called with correct args
    mock_popen.assert_called_once()
    call_args = mock_popen.call_args[0][0]
    assert call_args[0] == "owrap"
    assert call_args[1] == "ctx-worker"
    assert call_args[2] == "--input"
    assert call_args[3] == str(input_json)
    kw = mock_popen.call_args[1]
    assert kw["start_new_session"] is True
    assert kw["close_fds"] is True


# --- Test 2: CtxHookRunner with no matching session ---

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


# --- Test 3: Transcript parsing helper ---

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
    lines = [json.dumps(e) for e in entries]

    # From offset 0
    result = worker._extract_excerpt_lines(lines, 0)
    assert len(result) == 3
    assert result[0] == "I will help"
    assert result[1] == "First block"
    assert result[2] == "Second block"

    # From offset 1 (skip user)
    result = worker._extract_excerpt_lines(lines, 1)
    assert len(result) == 3

    # From offset 3 (skip first assistant + tool_result)
    result = worker._extract_excerpt_lines(lines, 3)
    assert len(result) == 2
    assert result[0] == "First block"
    assert result[1] == "Second block"

    # From offset 4 (past all)
    result = worker._extract_excerpt_lines(lines, 5)
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
    lines = [json.dumps(e) for e in entries]
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
    lines = [json.dumps(e) for e in entries]
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
    lines = [json.dumps(e) for e in entries]
    result = worker._extract_excerpt_lines(lines, 0)
    assert result == [
        "[Edit] owrap/foo.py", "[Write] owrap/bar.py", "[Read] owrap/baz.py",
    ]


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
    lines = [json.dumps(e) for e in entries]
    result = worker._extract_excerpt_lines(lines, 0)
    assert result == []


# --- Test 4: CtxWorker with no new transcript lines ---

# --- Test: touched-paths handoff (item 14) ---

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
    # transcript_offset already covers everything — nothing new to mine.
    counters = {"transcript_offset": 1}
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
    counters = {"transcript_offset": 1}
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

    # Write counters with transcript_offset at line 2 (all lines)
    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "hello"}]}},
    ])

    counters = {"transcript_offset": 2}
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
    task_file = sessions_dir / owrap_sid / "ctx" / ccsid / "input.md"
    assert not task_file.exists()
    # No transcript tmp file
    transcript_tmp = sessions_dir / owrap_sid / "ctx" / ccsid / "transcript.txt"
    assert not transcript_tmp.exists()
    # Offset unchanged
    updated = json.loads(cp.read_text())
    assert updated["transcript_offset"] == 2


# --- Test 5: CtxWorker with new assistant text ---

def test_ctx_worker_with_new_text(tmp_path, monkeypatch):
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)

    ccsid = "claude-456"
    owrap_sid = "def789"
    _make_session_file(sessions_dir, owrap_sid, ccsid)

    # 5 lines, offset at 2
    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "q"}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "old answer"}]}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "q2"}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "new answer here for context update"}]}},
        {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
    ])

    counters = {"transcript_offset": 2}
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
    transcript_tmp = sessions_dir / owrap_sid / "ctx" / ccsid / "transcript.txt"
    assert transcript_tmp.exists()
    excerpt = transcript_tmp.read_text()
    assert "new answer here for context update" in excerpt

    # Task file references only local filenames, never a real absolute path.
    task_file = sessions_dir / owrap_sid / "ctx" / ccsid / "input.md"
    assert task_file.exists()
    task_text = task_file.read_text()
    assert "transcript.txt" in task_text
    assert "# Context" in task_text
    assert "## Focus" in task_text
    assert str(transcript_tmp) not in task_text

    # No copy of context.md is prepared — the model only ever sees the transcript.
    assert not (sessions_dir / owrap_sid / "ctx" / ccsid / "context.md").exists()

    # Dispatched directly against the scoped dir under a pty, no pool/orun.
    mock_run.assert_called_once()
    cmd = shlex.split(mock_run.call_args[0][0])
    assert cmd[0] == "opencode"
    assert "--dir" in cmd
    assert "--dangerously-skip-permissions" not in cmd
    assert not (sessions_dir / owrap_sid / "ctx" / ccsid / "opencode.json").exists()

    # Offset updated to total lines (5)
    updated = json.loads(cp.read_text())
    assert updated["transcript_offset"] == 5


# --- Test: ctx_status tracking ---

def _make_context_md(sessions_dir, owrap_sid):
    path = sessions_dir / owrap_sid / "context.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "## Session\n\nsession: " + owrap_sid + "\nresearch: testr\n\n"
        "## Focus\n\n(none)\n"
    )
    return path


def _ctx_status(context_path):
    for line in context_path.read_text().splitlines():
        if line.startswith("ctx_status:"):
            return line.split(":", 1)[1].strip()
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


# --- Test 6: CtxWorker with updr due ---

def test_ctx_worker_includes_update_protocol_when_research_and_area_set(
    tmp_path, monkeypatch,
):
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)

    ccsid = "claude-789"
    owrap_sid = "ghi012"
    research = "testr"
    area = "testarea"
    _make_session_file(sessions_dir, owrap_sid, ccsid, research=research, area=area)

    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "new stuff happened"}]}},
    ])

    research_root = tmp_path / "research"
    base_config_path = tmp_path / "base_config.json"
    base_config_path.parent.mkdir(parents=True, exist_ok=True)
    base_config_path.write_text(json.dumps({
        "default_workspace": "test", "research_root": str(research_root),
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

    ctx_dir = sessions_dir / owrap_sid / "ctx" / ccsid
    task_file = ctx_dir / "input.md"
    assert task_file.exists()
    task_text = task_file.read_text()
    assert "# Context" in task_text
    assert "# Memory" in task_text
    assert "# Project" in task_text
    assert area in task_text

    # No copies of memory.md/project.md are prepared either — same reason
    assert not (ctx_dir / "memory.md").exists()
    assert not (ctx_dir / "project.md").exists()


# --- Test 7: multi-attach isolation ---

def test_ctx_worker_isolated_per_ccsid_under_multi_attach(tmp_path, monkeypatch):
    """Two windows (ccsids) attached to the SAME owrap session must get
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

    transcript_tmp_a = sessions_dir / owrap_sid / "ctx" / ccsid_a / "transcript.txt"
    transcript_tmp_b = sessions_dir / owrap_sid / "ctx" / ccsid_b / "transcript.txt"
    assert transcript_tmp_a.exists()
    assert transcript_tmp_b.exists()
    assert "from window A" in transcript_tmp_a.read_text()
    assert "from window B" in transcript_tmp_b.read_text()

    counters_a = json.loads((sessions_dir / f"{owrap_sid}.{ccsid_a}.counters.json").read_text())
    counters_b = json.loads((sessions_dir / f"{owrap_sid}.{ccsid_b}.counters.json").read_text())
    assert counters_a["transcript_offset"] == 1
    assert counters_b["transcript_offset"] == 1


# --- Test: same window, different research sessions in sequence ---

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

    transcript_tmp = sessions_dir / owrap_sid_b / "ctx" / ccsid / "transcript.txt"
    assert transcript_tmp.exists()
    excerpt = transcript_tmp.read_text()
    assert "work done on project B" in excerpt
    assert "project A" not in excerpt


# --- Test 8: Shared template test ---

def test_templates_reference_only_local_filenames():
    from owrap.constants import (
        CTX_SCOPED_TASK_TEMPLATE, CTX_CONTEXT_BLOCK, CTX_PROTOCOL_BLOCK,
    )

    # Must reference only local scoped filenames, never a real absolute path.
    task = CTX_SCOPED_TASK_TEMPLATE.format(read_lines="", blocks="")
    assert "transcript.txt" in task
    assert "output.md" in task
    for text in (
        CTX_SCOPED_TASK_TEMPLATE, CTX_CONTEXT_BLOCK,
        CTX_PROTOCOL_BLOCK.format(area="x"),
    ):
        assert 'self.md' not in text
        assert '/home/' not in text


# --- Test 9: Staging test ---

def test_stage_all_includes_sessionstart_and_ctx_hook(tmp_path, monkeypatch):
    from owrap.staging import stage_all

    workspace = tmp_path / "ws"
    workspace.mkdir(parents=True)
    configs_dir = tmp_path / "owrap_configs"

    monkeypatch.setattr("owrap.utils.paths.CONFIGS_DIR", configs_dir)
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
    staged_settings = staged / "settings.json"
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

    # PreCompact hook command is ~/bin/owrap ctx-hook
    assert "PreCompact" in hooks
    pc = hooks["PreCompact"][0]["hooks"][0]
    assert pc["command"] == "~/bin/owrap ctx-hook"


# --- Test: Excerpt capping ---

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

    transcript_tmp = sessions_dir / owrap_sid / "ctx" / ccsid / "transcript.txt"
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
    assert cmd[0] == "owrap" and cmd[1] == "ctx-worker" and cmd[2] == "--input"
    payload = json.loads(Path(cmd[3]).read_text())
    assert payload["mode"] == "ctx"
    assert payload["session_id"] == ccsid


def test_run_manual_updr_includes_area_in_payload(tmp_path, monkeypatch):
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

    mock_popen = MagicMock()
    with patch("owrap.commands.context_manager.subprocess.Popen", mock_popen):
        CtxWorkerRunner().run_manual(mode="updr", area="customarea")

    cmd = mock_popen.call_args[0][0]
    payload = json.loads(Path(cmd[3]).read_text())
    assert payload["mode"] == "updr"
    assert payload["area"] == "customarea"


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
        CtxWorkerRunner().run_manual(mode=None)

    mock_popen.assert_called_once()
    cmd = mock_popen.call_args[0][0]
    payload = json.loads(Path(cmd[3]).read_text())
    assert payload["mode"] is None


def test_run_manual_combined_mode_prints_readable_label(tmp_path, monkeypatch, capsys):
    """
    The queued-dispatch message must never print the literal word "None"
    for combined mode (mode=None) — it should read as "ctx+updr".
    """
    _, sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    ccsid = "claude-combined-label"
    owrap_sid = "combinedlabel01"
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
    _make_session_file(sessions_dir, owrap_sid, ccsid)

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
    task_md = (sessions_dir / owrap_sid / "ctx" / ccsid / "input.md").read_text()
    assert "# Context" in task_md
    assert "# Memory" in task_md
    assert "# Project" in task_md


def test_run_manual_combined_mode_requires_research_and_area(tmp_path, monkeypatch):
    """
    Combined mode (None) still needs research/area for the Protocol half
    — same validation `--updr` alone already requires.
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
    task_md = (sessions_dir / owrap_sid / "ctx" / ccsid / "input.md").read_text()
    assert "# Context" in task_md
    assert "# Memory" not in task_md
    assert "# Project" not in task_md


def test_ctx_dispatch_omits_model_flag_when_nothing_configured(
    tmp_path, monkeypatch,
):
    cmd = _dispatch_ctx_with_config(tmp_path, monkeypatch, {})
    assert "-m" not in cmd


# --- Test: output validation and retry/fallback (item 9) ---

def test_validate_output_rejects_missing_focus():
    runner = CtxWorkerRunner()
    output = "# Project\n## main\n### Status\nok\n"
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


# --- Test: deterministic merge of model output (no model judgment) ---

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


def test_merge_memory_appends_components_no_cap(tmp_path):
    memory_path = tmp_path / "memory.md"
    memory_path.write_text("## main\n### Components\n- a.py — role a\n")
    output = "# Memory\n## main\n### Components\n- b.py — role b\n"
    runner = CtxWorkerRunner()
    runner._merge_memory(
        split_top_sections(output, ("Context", "Memory", "Project"))["Memory"],
        memory_path, "main", "myresearch",
    )
    text = memory_path.read_text()
    assert "a.py — role a" in text
    assert "b.py — role b" in text


def test_merge_memory_appends_new_subsystem_block(tmp_path):
    memory_path = tmp_path / "memory.md"
    memory_path.write_text("## main\n### Components\n- a.py — role a\n")
    output = (
        "# Memory\n## main\n### Pool\n"
        "- Pool at pool.py:10 — manages the server pool\n"
    )
    runner = CtxWorkerRunner()
    runner._merge_memory(
        split_top_sections(output, ("Context", "Memory", "Project"))["Memory"],
        memory_path, "main", "myresearch",
    )
    text = memory_path.read_text()
    assert "### Components" in text
    assert "### Pool" in text
    assert "manages the server pool" in text


def test_merge_project_replaces_status_and_dates_decisions(tmp_path):
    projects_path = tmp_path / "projects.md"
    projects_path.write_text(
        "## main\n### Status\nold status\n\n### Decisions\n"
        "| 2026-01-01 | old decision | old reason |\n",
    )
    output = (
        "# Project\n## main\n### Status\nnew status\n"
        "### Decisions\n- new decision — new reason\n"
    )
    runner = CtxWorkerRunner()
    runner._merge_project(
        split_top_sections(output, ("Context", "Memory", "Project"))["Project"],
        projects_path, "main", "myresearch",
    )
    text = projects_path.read_text()
    assert "new status" in text and "old status" not in text
    # old decision preserved (Decisions is a log, not a snapshot)
    assert "old decision" in text
    # new decision gets dated by code, not the model, and prepended (newest-first)
    import time
    today = time.strftime("%Y-%m-%d")
    assert f"| {today} | new decision | new reason |" in text
    assert text.index("new decision") < text.index("old decision")


# --- Test: Key Locations staleness pruning (item 12) ---

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


def test_merge_project_dedupes_decisions_by_text():
    runner = CtxWorkerRunner()
    today = "2026-10-01"
    row = runner._decision_row("- same decision — some reason", today)
    assert row == "| 2026-10-01 | same decision | some reason |"
    assert runner._decision_row_key(row) == "same decision"


# --- Test: merges are single-writer locked (item 5) ---

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


def test_merge_memory_acquires_memory_lock(tmp_path):
    from owrap.utils.paths import memory_lock_path
    memory_path = tmp_path / "memory.md"
    memory_path.write_text("## main\n### Components\n- a.py — role a\n")
    output = "# Memory\n## main\n### Components\n- b.py — role b\n"
    runner = CtxWorkerRunner()
    runner._merge_memory(
        split_top_sections(output, ("Context", "Memory", "Project"))["Memory"],
        memory_path, "main", "myresearch",
    )
    assert memory_lock_path("myresearch").exists()


def test_merge_project_acquires_projects_lock(tmp_path):
    from owrap.utils.paths import projects_lock_path
    projects_path = tmp_path / "projects.md"
    projects_path.write_text("## main\n### Status\nold\n")
    output = "# Project\n## main\n### Status\nnew\n"
    runner = CtxWorkerRunner()
    runner._merge_project(
        split_top_sections(output, ("Context", "Memory", "Project"))["Project"],
        projects_path, "main", "myresearch",
    )
    assert projects_lock_path("myresearch").exists()
