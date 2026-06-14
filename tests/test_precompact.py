import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from owrap.commands.precompact import PrecompactRunner
from owrap.commands.precompact import PrecompactWorkerRunner, MAX_EXCERPT_CHARS


# --- Helpers ---

def _make_hook_stdin(session_id, transcript_path="/tmp/transcript.jsonl", cwd="/tmp"):
    return json.dumps({
        "session_id": session_id,
        "transcript_path": transcript_path,
        "cwd": cwd,
    })


def _make_session_file(sessions_dir, owrap_sid, claude_session_id, research="testr", area="testarea"):
    sf = sessions_dir / f"{owrap_sid}.session"
    sf.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"session_id={owrap_sid}",
        f"claude_session_id={claude_session_id}",
        f"research={research}",
        f"area={area}",
    ]
    sf.write_text("\n".join(lines) + "\n")
    return sf


def _make_transcript_jsonl(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e) for e in entries]
    path.write_text("\n".join(lines) + "\n")


# --- Test 1: PrecompactRunner with matching session ---

def test_precompact_runner_spawns_worker(tmp_path, monkeypatch):
    docs_dir = tmp_path / "docs"
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr("owrap.utils.paths.DOCS_DIR", docs_dir)
    monkeypatch.setattr("owrap.utils.paths.SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr("owrap.utils.session_resolver.SESSIONS_DIR", sessions_dir)

    claude_sid = "claude-123"
    owrap_sid = "abc123"
    _make_session_file(sessions_dir, owrap_sid, claude_sid)

    mock_popen = MagicMock()
    with patch("owrap.commands.precompact.subprocess.Popen", mock_popen), \
         patch("owrap.commands.precompact.sys.stdin.read") as mock_stdin:
        mock_stdin.return_value = _make_hook_stdin(claude_sid)
        with pytest.raises(SystemExit) as exc_info:
            PrecompactRunner().run()
        assert exc_info.value.code == 0

    # Check that the input JSON was written
    input_json = sessions_dir / owrap_sid / "precompact" / "precompact.json"
    assert input_json.exists()
    data = json.loads(input_json.read_text())
    assert data["session_id"] == claude_sid

    # Check Popen was called with correct args
    mock_popen.assert_called_once()
    call_args = mock_popen.call_args[0][0]
    assert call_args[0] == "owrap"
    assert call_args[1] == "precompact-worker"
    assert call_args[2] == "--input"
    assert call_args[3] == str(input_json)
    kw = mock_popen.call_args[1]
    assert kw["start_new_session"] is True
    assert kw["close_fds"] is True


# --- Test 2: PrecompactRunner with no matching session ---

def test_precompact_runner_no_matching_session(tmp_path, monkeypatch):
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr("owrap.utils.paths.DOCS_DIR", tmp_path / "docs")
    monkeypatch.setattr("owrap.utils.session_resolver.SESSIONS_DIR", sessions_dir)

    mock_popen = MagicMock()
    with patch("owrap.commands.precompact.subprocess.Popen", mock_popen), \
         patch("owrap.commands.precompact.sys.stdin.read") as mock_stdin:
        mock_stdin.return_value = _make_hook_stdin("unknown-ccsid")
        with pytest.raises(SystemExit) as exc_info:
            PrecompactRunner().run()
        assert exc_info.value.code == 0

    mock_popen.assert_not_called()


# --- Test 3: Transcript parsing helper ---

def test_extract_assistant_text():
    worker = PrecompactWorkerRunner()
    entries = [
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "hello"}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "I will help"}]}},
        {"type": "tool_result", "tool_use_id": "t1", "content": "result"},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "First block"},
            {"type": "tool_use", "name": "read", "input": {}},
            {"type": "text", "text": "Second block"},
        ]}},
    ]
    lines = [json.dumps(e) for e in entries]

    # From offset 0
    result = worker._extract_assistant_text(lines, 0)
    assert len(result) == 3
    assert result[0] == "I will help"
    assert result[1] == "First block"
    assert result[2] == "Second block"

    # From offset 1 (skip user)
    result = worker._extract_assistant_text(lines, 1)
    assert len(result) == 3

    # From offset 3 (skip first assistant + tool_result)
    result = worker._extract_assistant_text(lines, 3)
    assert len(result) == 2
    assert result[0] == "First block"
    assert result[1] == "Second block"

    # From offset 4 (past all)
    result = worker._extract_assistant_text(lines, 5)
    assert len(result) == 0


# --- Test 4: PrecompactWorker with no new transcript lines ---

def test_precompact_nothing_new(tmp_path, monkeypatch):
    docs_dir = tmp_path / "docs"
    sessions_dir = tmp_path / "sessions"
    counters_dir = sessions_dir

    monkeypatch.setattr("owrap.utils.paths.DOCS_DIR", docs_dir)
    monkeypatch.setattr("owrap.utils.paths.SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr("owrap.utils.session_resolver.SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr("owrap.utils.donow.COUNTERS_DIR", counters_dir)

    claude_sid = "claude-123"
    owrap_sid = "abc456"
    _make_session_file(sessions_dir, owrap_sid, claude_sid)

    # Write counters with transcript_offset at line 2 (all lines)
    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "hello"}]}},
    ])

    counters = {"transcript_offset": 2}
    cp = counters_dir / f"{owrap_sid}.counters.json"
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(counters))

    input_path = tmp_path / "hook_input.json"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(json.dumps({
        "session_id": claude_sid,
        "transcript_path": str(transcript),
    }))

    mock_run = MagicMock()
    with patch("owrap.commands.precompact.subprocess.run", mock_run):
        with pytest.raises(SystemExit) as exc_info:
            PrecompactWorkerRunner().run(input_path=input_path)
        assert exc_info.value.code == 0

    # No orun dispatch
    mock_run.assert_not_called()
    # No task file
    task_file = sessions_dir / owrap_sid / "run" / "input_precompact.md"
    assert not task_file.exists()
    # No transcript tmp file
    transcript_tmp = sessions_dir / owrap_sid / "precompact" / "precompact_transcript.txt"
    assert not transcript_tmp.exists()
    # Offset unchanged
    updated = json.loads(cp.read_text())
    assert updated["transcript_offset"] == 2


# --- Test 5: PrecompactWorker with new assistant text ---

def test_precompact_with_new_text(tmp_path, monkeypatch):
    docs_dir = tmp_path / "docs"
    sessions_dir = tmp_path / "sessions"
    counters_dir = sessions_dir

    monkeypatch.setattr("owrap.utils.paths.DOCS_DIR", docs_dir)
    monkeypatch.setattr("owrap.utils.paths.SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr("owrap.utils.session_resolver.SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr("owrap.utils.donow.COUNTERS_DIR", counters_dir)

    claude_sid = "claude-456"
    owrap_sid = "def789"
    _make_session_file(sessions_dir, owrap_sid, claude_sid)

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
    cp = counters_dir / f"{owrap_sid}.counters.json"
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(counters))

    input_path = tmp_path / "hook_input.json"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(json.dumps({
        "session_id": claude_sid,
        "transcript_path": str(transcript),
    }))

    mock_run = MagicMock(return_value=MagicMock(returncode=0))
    with patch("owrap.commands.precompact.subprocess.run", mock_run):
        runner = PrecompactWorkerRunner()
        runner.run(input_path=input_path)

    # Transcript tmp file written
    transcript_tmp = sessions_dir / owrap_sid / "precompact" / "precompact_transcript.txt"
    assert transcript_tmp.exists()
    excerpt = transcript_tmp.read_text()
    assert "new answer here for context update" in excerpt

    # Task file written with self-contained instructions
    task_file = sessions_dir / owrap_sid / "run" / "input_precompact.md"
    assert task_file.exists()
    task_text = task_file.read_text()
    assert "Update Context (pre-compaction)" in task_text
    assert str(transcript_tmp) in task_text
    assert "Do not touch" in task_text  # self-contained, no reference to self.md

    # orun dispatched with --input
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd[0].endswith("orun")
    assert "--input" in cmd
    assert str(task_file) in cmd

    # Offset updated to total lines (5)
    updated = json.loads(cp.read_text())
    assert updated["transcript_offset"] == 5


# --- Test 6: PrecompactWorker with updr due ---

def test_precompact_with_updr_due(tmp_path, monkeypatch):
    docs_dir = tmp_path / "docs"
    sessions_dir = tmp_path / "sessions"
    counters_dir = sessions_dir

    monkeypatch.setattr("owrap.utils.paths.DOCS_DIR", docs_dir)
    monkeypatch.setattr("owrap.utils.paths.SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr("owrap.utils.session_resolver.SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr("owrap.utils.donow.COUNTERS_DIR", counters_dir)

    claude_sid = "claude-789"
    owrap_sid = "ghi012"
    research = "testr"
    area = "testarea"
    _make_session_file(sessions_dir, owrap_sid, claude_sid, research=research, area=area)

    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "new stuff happened"}]}},
    ])

    # Set counters with plan_count >= 1 so updr is due
    cp = counters_dir / f"{owrap_sid}.counters.json"
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps({"plan_count": 5}))

    # Mock base config with low updr thresholds
    base_config_path = tmp_path / "base_config.json"
    base_config_path.parent.mkdir(parents=True, exist_ok=True)
    base_config_path.write_text(json.dumps({
        "default_workspace": "test",
        "updr_every_plans": 1,
        "updr_every_steps": 100,
    }))

    input_path = tmp_path / "hook_input.json"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(json.dumps({
        "session_id": claude_sid,
        "transcript_path": str(transcript),
    }))

    mock_run = MagicMock(return_value=MagicMock(returncode=0))
    with patch("owrap.utils.paths.BASE_CONFIG_FILE", base_config_path), \
         patch("owrap.utils.donow.context_path") as mock_ctx_path, \
         patch("owrap.utils.donow.get_plan_path") as mock_plan_path, \
         patch("owrap.commands.precompact.subprocess.run", mock_run):
        # context file must exist for check_donow (with precompact it skips missing check but we mock anyway)
        ctx_path = tmp_path / "context.md"
        ctx_path.write_text("## Focus\n\n## Active Plan\n\n## Key Locations\n\n## Decisions\n\n## Environment\n")
        mock_ctx_path.return_value = ctx_path
        mock_plan_path.return_value = tmp_path / "plan.md"
        (tmp_path / "plan.md").write_text("## [ACTIVE] 1\n1. [ ] step\n")
        runner = PrecompactWorkerRunner()
        runner.run(input_path=input_path)

    task_file = sessions_dir / owrap_sid / "run" / "input_precompact.md"
    assert task_file.exists()
    task_text = task_file.read_text()
    assert "Update Context (pre-compaction)" in task_text
    assert "Update Protocol (pre-compaction)" in task_text
    assert research in task_text
    assert area in task_text


# --- Test 7: Shared template test ---

def test_templates_match_self_md_verbatim():
    from owrap.constants import PRE_COMPACT_CTX_TEMPLATE, PRE_COMPACT_UPDR_TEMPLATE

    # Pre-compact templates must use format vars, not hardcoded paths
    assert '{context_path}' in PRE_COMPACT_CTX_TEMPLATE
    assert '{memory_path}' in PRE_COMPACT_UPDR_TEMPLATE
    assert '{projects_path}' in PRE_COMPACT_UPDR_TEMPLATE

    # Must not reference self.md or hardcoded /home paths
    assert 'self.md' not in PRE_COMPACT_CTX_TEMPLATE
    assert 'self.md' not in PRE_COMPACT_UPDR_TEMPLATE
    assert '/home/' not in PRE_COMPACT_CTX_TEMPLATE
    assert '/home/' not in PRE_COMPACT_UPDR_TEMPLATE


# --- Test 8: Staging test ---

def test_stage_all_includes_sessionstart_and_precompact(tmp_path, monkeypatch):
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

    # PreCompact hook command is ~/bin/owrap precompact
    assert "PreCompact" in hooks
    pc = hooks["PreCompact"][0]["hooks"][0]
    assert pc["command"] == "~/bin/owrap precompact"


# --- Test: Excerpt capping ---

def test_excerpt_capped_at_max_chars(tmp_path, monkeypatch):
    docs_dir = tmp_path / "docs"
    sessions_dir = tmp_path / "sessions"
    counters_dir = sessions_dir

    monkeypatch.setattr("owrap.utils.paths.DOCS_DIR", docs_dir)
    monkeypatch.setattr("owrap.utils.paths.SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr("owrap.utils.session_resolver.SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr("owrap.utils.donow.COUNTERS_DIR", counters_dir)

    claude_sid = "claude-long"
    owrap_sid = "long001"
    _make_session_file(sessions_dir, owrap_sid, claude_sid)

    # Generate assistant text longer than MAX_EXCERPT_CHARS
    long_text = "x" * (MAX_EXCERPT_CHARS + 2000)
    transcript = tmp_path / "transcript.jsonl"
    _make_transcript_jsonl(transcript, [
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": long_text}]}},
    ])

    input_path = tmp_path / "hook_input.json"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(json.dumps({
        "session_id": claude_sid,
        "transcript_path": str(transcript),
    }))

    mock_run = MagicMock(return_value=MagicMock(returncode=0))
    with patch("owrap.commands.precompact.subprocess.run", mock_run):
        runner = PrecompactWorkerRunner()
        runner.run(input_path=input_path)

    transcript_tmp = sessions_dir / owrap_sid / "precompact" / "precompact_transcript.txt"
    assert transcript_tmp.exists()
    excerpt = transcript_tmp.read_text()
    assert len(excerpt) <= MAX_EXCERPT_CHARS
    # Should contain the tail of the long text
    assert excerpt.endswith("x")
