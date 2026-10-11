"""
The `get` coverage added to close the gaps found while auditing the
old `owrap get <what>` command against the new kind system: `Self`
(home/self/opencode -- facts that need no session, plus config/plan/
input/output -- Session/Project/dispatch-scoped data `Self` serves
anyway since none of it has a kind of its own), `Session._default_get`
(identity table), `Agent._default_get` (digest dump, distinct from
`Agent.get(task_id)`), and `Updr.get("memory")` (every linked
repository, not just one). Each has real branching or multi-value
output worth pinning down beyond reading the code.
"""
import os
import time

import pytest

from owrap.kind.dispatch.agent import Agent
from owrap.kind.op.self import Self
from owrap.kind.run.session import Session
from owrap.kind.dispatch.updr import Updr


# Self -- do (self.md content) / get home / get opencode [reason]

@pytest.fixture
def self_setup(tmp_path, monkeypatch):
    self_path = tmp_path / "self.md"
    self_path.write_text("# Self reference\n\nsome content\n")
    monkeypatch.setattr("owrap.kind.op.self.get_self_path", lambda: self_path)
    monkeypatch.setattr("owrap.kind.op.self.OWRAP_HOME", tmp_path / "home")
    return self_path


def test_do_prints_self_md_content(self_setup, capsys):
    Self().do()
    assert capsys.readouterr().out.strip() == "# Self reference\n\nsome content"


def test_do_fails_cleanly_when_nothing_staged(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "owrap.kind.op.self.get_self_path", lambda: tmp_path / "missing.md",
    )
    with pytest.raises(SystemExit) as exc:
        Self().do()
    assert exc.value.code == 2
    assert "no staged self file" in capsys.readouterr().out


def test_get_bare_matches_do(self_setup, capsys):
    Self().get()
    assert capsys.readouterr().out.strip() == "# Self reference\n\nsome content"


def test_get_home_prints_owrap_home(self_setup, capsys, tmp_path):
    Self().get("home")
    assert capsys.readouterr().out.strip() == str(tmp_path / "home")


def test_get_opencode_reports_up_when_never_written(self_setup, monkeypatch, capsys):
    monkeypatch.setattr(
        "owrap.kind.op.self.read_opencode_status_detail",
        lambda: {"status": "up", "reason": None, "since": None},
    )
    Self().get("opencode")
    assert capsys.readouterr().out.strip() == "up"


def test_get_opencode_reason_reports_down_reason(self_setup, monkeypatch, capsys):
    monkeypatch.setattr(
        "owrap.kind.op.self.read_opencode_status_detail",
        lambda: {"status": "down", "reason": "TLS handshake timeout", "since": 1},
    )
    Self().get("opencode", "reason")
    assert capsys.readouterr().out.strip() == "TLS handshake timeout"


def test_get_unknown_target_shows_usage(self_setup, capsys):
    with pytest.raises(SystemExit) as exc:
        Self().get("bogus")
    assert exc.value.code == 2
    assert "Usage: owrap get self" in capsys.readouterr().out


# Self -- get config/plan/input (Session/Project-scoped data, no kind of its own)

def test_get_config_prints_the_attached_sessions_effective_config(
    monkeypatch, capsys,
):
    """
    Reports the merged base+workspace config, not just the
    workspace override file.
    """
    monkeypatch.setenv("SESSION_ID", "abc123")
    monkeypatch.setattr(
        "owrap.kind.op.self.current_workspace", lambda: "marl",
    )
    monkeypatch.setattr(
        "owrap.kind.op.self._read_config",
        lambda workspace=None: {"workspace": workspace, "allow_all": True},
    )
    Self().get("config")
    out = capsys.readouterr().out
    assert '"workspace": "marl"' in out
    assert '"allow_all": true' in out


def test_get_config_fails_cleanly_with_no_session_id(monkeypatch, capsys):
    monkeypatch.delenv("SESSION_ID", raising=False)
    with pytest.raises(SystemExit) as exc:
        Self().get("config")
    assert exc.value.code == 2
    assert "no SESSION_ID" in capsys.readouterr().out


def test_get_config_fails_cleanly_when_workspace_has_no_config(monkeypatch, capsys):
    monkeypatch.setenv("SESSION_ID", "abc123")
    monkeypatch.setattr("owrap.kind.op.self.current_workspace", lambda: "")
    monkeypatch.setattr(
        "owrap.kind.op.self._read_config", lambda workspace=None: {},
    )
    with pytest.raises(SystemExit) as exc:
        Self().get("config")
    assert exc.value.code == 2
    assert "no config found" in capsys.readouterr().out


def test_get_plan_prints_path_and_preview(monkeypatch, tmp_path, capsys):
    plan_path = tmp_path / "plan.md"
    plan_path.write_text("# Plan\n\n- [ ] step one\n")
    monkeypatch.setenv("SESSION_ID", "abc123")
    monkeypatch.setattr(
        "owrap.kind.op.self.get_plan_path", lambda sid: plan_path,
    )
    Self().get("plan")
    out = capsys.readouterr().out
    assert str(plan_path) in out
    assert "step one" in out


def test_get_input_reports_no_input_yet_when_queue_is_empty(
    monkeypatch, tmp_path, capsys,
):
    missing = tmp_path / "input.md"
    monkeypatch.setenv("SESSION_ID", "abc123")
    monkeypatch.setattr(
        "owrap.kind.op.self.session_input", lambda sid: missing,
    )
    Self().get("input")
    out = capsys.readouterr().out
    assert str(missing) in out
    assert "(no input yet)" in out


# Self -- get output <msg|task|agent|exec> (latest only; an id is each kind's own get)

def test_get_output_exec_reports_single_fixed_path(monkeypatch, tmp_path, capsys):
    path = tmp_path / "exec.log"
    path.write_text("exec output here")
    monkeypatch.setenv("SESSION_ID", "sid1")
    monkeypatch.setattr(
        "owrap.kind.op.self.session_exec_output_path", lambda sid: path,
    )
    Self().get("output", "exec")
    out = capsys.readouterr().out
    assert str(path) in out
    assert "exec output here" in out


def test_get_output_task_reports_most_recently_modified_file(
    monkeypatch, tmp_path, capsys,
):
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "r_old.log").write_text("older")
    newest = task_dir / "r_new.log"
    newest.write_text("newest content")
    os.utime(newest, (time.time() + 10, time.time() + 10))
    monkeypatch.setenv("SESSION_ID", "sid1")
    monkeypatch.setattr(
        "owrap.kind.op.self.session_task_output_dir", lambda sid: task_dir,
    )
    Self().get("output", "task")
    out = capsys.readouterr().out
    assert str(newest) in out
    assert "newest content" in out


def test_get_output_reports_none_yet_when_directory_is_empty(
    monkeypatch, tmp_path, capsys,
):
    monkeypatch.setenv("SESSION_ID", "sid1")
    monkeypatch.setattr(
        "owrap.kind.op.self.session_msg_output_dir", lambda sid: tmp_path / "nope",
    )
    Self().get("output", "msg")
    out = capsys.readouterr().out
    assert "no msg output yet for session sid1" in out


def test_get_output_rejects_unknown_kind(monkeypatch, capsys):
    monkeypatch.setenv("SESSION_ID", "sid1")
    with pytest.raises(SystemExit) as exc:
        Self().get("output", "bogus")
    assert exc.value.code == 2
    assert "Usage: owrap get self" in capsys.readouterr().out


# Session._default_get -- identity-field table

def test_session_default_get_prints_identity_table(monkeypatch, tmp_path, capsys):
    sessions = tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
    sfile = sessions / "abc123" / ".session"
    sfile.parent.mkdir(parents=True)
    sfile.write_text(
        "session_id=abc123\ntarget_kind=project\nproject_id=demo\n"
        "subproject_id=\nworkspace=test\nstarted=2026-01-01\n",
    )
    monkeypatch.setattr("owrap.kind.run.session.session_file", lambda sid: sfile)
    monkeypatch.setenv("SESSION_ID", "abc123")

    Session()._default_get()
    out = capsys.readouterr().out
    assert "session_id" in out and "abc123" in out
    assert "project_id" in out and "demo" in out
    assert "target_kind" in out and "project" in out


def test_session_default_get_fails_cleanly_with_no_session_id(monkeypatch, capsys):
    monkeypatch.delenv("SESSION_ID", raising=False)
    with pytest.raises(SystemExit) as exc:
        Session()._default_get()
    assert exc.value.code == 2
    assert "no SESSION_ID" in capsys.readouterr().out


# Agent._default_get -- the session's digest, distinct from get(task_id)

def test_agent_default_get_prints_digest_content(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("OWRAP_SESSION", "sid1")
    log_path = tmp_path / "output.log"
    log_path.write_text("## [a:1] 2026-01-01\n**Summary:** did the thing\n")
    monkeypatch.setattr(
        "owrap.kind.dispatch.agent.session_agent_log_path", lambda sid: log_path,
    )
    Agent()._default_get()
    out = capsys.readouterr().out
    assert "did the thing" in out
    assert str(log_path) in out


def test_agent_default_get_fails_cleanly_with_no_output_yet(
    monkeypatch, tmp_path, capsys,
):
    monkeypatch.setenv("OWRAP_SESSION", "sid2")
    monkeypatch.setattr(
        "owrap.kind.dispatch.agent.session_agent_log_path",
        lambda sid: tmp_path / "missing.log",
    )
    with pytest.raises(SystemExit) as exc:
        Agent()._default_get()
    assert exc.value.code == 2
    assert "no agent output for session sid2" in capsys.readouterr().out


def test_agent_default_get_fails_cleanly_with_no_active_session(monkeypatch, capsys):
    monkeypatch.delenv("OWRAP_SESSION", raising=False)
    with pytest.raises(SystemExit) as exc:
        Agent()._default_get()
    assert exc.value.code == 2
    assert "no active session" in capsys.readouterr().out


# Updr.get("memory") -- every linked repository, not just the first

@pytest.fixture
def updr_memory_setup(tmp_path, monkeypatch):
    root = tmp_path / "research"
    project = root / "projects" / "proj"
    project.mkdir(parents=True)
    (project / "proj.yaml").write_text(
        "schema_version: 1\nkind: project\nid: proj\nmain: main.md\n"
        "repositories: [repo1, repo2]\n",
    )
    (project / "main.md").write_text("# proj\n")
    for name, text in (("repo1", "first repo"), ("repo2", "second repo")):
        repo_dir = root / "repositories" / name
        repo_dir.mkdir(parents=True)
        (repo_dir / f"{name}.yaml").write_text(
            f"schema_version: 1\nkind: repository\nid: {name}\nmain: memory.md\n",
        )
        (repo_dir / "memory.md").write_text(f"# {name}\n{text}\n")
    monkeypatch.setattr(
        "owrap.utils.memory.records.get_workspace_config",
        lambda workspace: {"docs_root": str(root)},
    )
    sessions = tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
    sfile = sessions / "abc123.session"
    sfile.write_text(
        "session_id=abc123\ntarget_kind=project\nproject_id=proj\nworkspace=test\n",
    )
    monkeypatch.setattr("owrap.kind.dispatch.updr.session_file", lambda sid: sfile)
    monkeypatch.setenv("SESSION_ID", "abc123")
    return root


def test_updr_get_memory_prints_every_linked_repository(updr_memory_setup, capsys):
    Updr().get("memory")
    out = capsys.readouterr().out
    assert "first repo" in out
    assert "second repo" in out
    assert out.count("# memory:") == 2


def test_updr_get_rejects_anything_other_than_memory(updr_memory_setup, capsys):
    with pytest.raises(SystemExit) as exc:
        Updr().get("bogus")
    assert exc.value.code == 2
    assert "Usage: owrap get updr" in capsys.readouterr().out
