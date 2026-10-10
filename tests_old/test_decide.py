import time

import pytest

from owrap.commands.decide import DecideRunner


def _project(tmp_path, monkeypatch, decisions_body=""):
    """
    Create a minimal project record (<id>.yaml + main.md) with Goals and
    Notes sections flanking Decisions, so tests can assert those stay
    untouched by decision edits.
    """
    root = tmp_path / "research"
    project = root / "projects" / "proj"
    project.mkdir(parents=True)
    (project / "proj.yaml").write_text(
        "schema_version: 1\nkind: project\nid: proj\nmain: main.md\n",
    )
    (project / "main.md").write_text(
        f"# proj\n\n## Goals\n\nKeep this.\n\n"
        f"## Decisions\n\n{decisions_body}\n## Notes\n\nKeep this too.\n",
    )
    monkeypatch.setattr(
        "owrap.utils.memory.records.get_workspace_config",
        lambda workspace: {"docs_root": str(root)},
    )
    return project


def _session(tmp_path, monkeypatch, sid="abc123", **fields):
    sessions = tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
    body = "".join(f"{k}={v}\n" for k, v in fields.items())
    sfile = sessions / f"{sid}.session"
    sfile.write_text(f"session_id={sid}\n{body}")
    monkeypatch.setattr(
        "owrap.commands.decide.resolve_session_or_exit", lambda token: sid,
    )
    monkeypatch.setattr("owrap.commands.decide.session_file", lambda s: sfile)
    monkeypatch.delenv("SESSION_ID", raising=False)
    return sfile


@pytest.fixture
def decide_setup(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch)
    _session(
        tmp_path, monkeypatch,
        target_kind="project", project_id="proj", workspace="test",
    )
    return project


def _decision_lines(project):
    text = (project / "main.md").read_text()
    section = text.split("## Decisions", 1)[1].split("## Notes", 1)[0]
    return [line for line in section.splitlines() if line.startswith("- ")]


class TestDecideRunner:
    def test_adds_timestamped_entry(self, decide_setup, monkeypatch):
        monkeypatch.setattr(
            "owrap.utils.memory.records.time.strftime", lambda _: "2026-10-07 10:00",
        )
        DecideRunner().run("abc123", "Keep the dev/live split")

        lines = _decision_lines(decide_setup)
        assert lines == ["- 2026-10-07 10:00 — Keep the dev/live split"]

    def test_new_entries_go_newest_first(self, decide_setup, monkeypatch):
        stamps = iter(["2026-10-07 10:00", "2026-10-07 10:05"])
        monkeypatch.setattr(
            "owrap.utils.memory.records.time.strftime", lambda _: next(stamps),
        )
        DecideRunner().run("abc123", "first")
        DecideRunner().run("abc123", "second")

        lines = _decision_lines(decide_setup)
        assert lines == [
            "- 2026-10-07 10:05 — second",
            "- 2026-10-07 10:00 — first",
        ]

    def test_unrelated_sections_preserved(self, decide_setup):
        DecideRunner().run("abc123", "text")
        text = (decide_setup / "main.md").read_text()
        assert "Keep this.\n" in text
        assert "Keep this too.\n" in text

    def test_bumps_project_last_updated(self, decide_setup):
        before = time.time()
        DecideRunner().run("abc123", "text")
        import yaml
        record = yaml.safe_load((decide_setup / "proj.yaml").read_text())
        assert record["last_updated"] >= before

    def test_prints_confirmation(self, decide_setup, capsys):
        DecideRunner().run("abc123", "Keep the dev/live split")
        out = capsys.readouterr().out
        assert "DECISION added to" in out
        assert "Keep the dev/live split" in out

    def test_missing_text_exits_nonzero(self, decide_setup, capsys):
        with pytest.raises(SystemExit) as exc:
            DecideRunner().run("abc123", None)
        assert exc.value.code == 2
        assert "Usage: owrap decide" in capsys.readouterr().out

    def test_empty_target_falls_back_to_attached_session(
        self, tmp_path, monkeypatch,
    ):
        project = _project(tmp_path, monkeypatch)
        sfile = _session(
            tmp_path, monkeypatch,
            target_kind="project", project_id="proj", workspace="test",
        )
        monkeypatch.setenv("SESSION_ID", "abc123")
        monkeypatch.setattr(
            "owrap.commands.decide.resolve_session_or_exit",
            lambda token: (_ for _ in ()).throw(AssertionError("should not resolve")),
        )
        monkeypatch.setattr("owrap.commands.decide.session_file", lambda s: sfile)

        DecideRunner().run(None, "text")

        assert _decision_lines(project)

    def test_empty_target_no_session_exits_nonzero(self, decide_setup, capsys):
        with pytest.raises(SystemExit) as exc:
            DecideRunner().run(None, "text")
        assert exc.value.code == 2
        assert "no target given and no session attached" in capsys.readouterr().out


    def test_fresh_empty_decisions_section_gets_one_blank_line(
        self, tmp_path, monkeypatch,
    ):
        from owrap.utils.memory.records import _project_stub_text
        root = tmp_path / "research"
        project = root / "projects" / "proj"
        project.mkdir(parents=True)
        (project / "proj.yaml").write_text(
            "schema_version: 1\nkind: project\nid: proj\nmain: main.md\n",
        )
        (project / "main.md").write_text(_project_stub_text("proj"))
        monkeypatch.setattr(
            "owrap.utils.memory.records.get_workspace_config",
            lambda workspace: {"docs_root": str(root)},
        )
        _session(
            tmp_path, monkeypatch,
            target_kind="project", project_id="proj", workspace="test",
        )

        DecideRunner().run("abc123", "first decision")

        text = project.joinpath("main.md").read_text()
        assert "## Decisions\n\n- " in text
        assert "## Decisions\n\n\n- " not in text
        assert _decision_lines(project) == [
            f"- {time.strftime('%Y-%m-%d %H:%M')} — first decision",
        ]


class TestDecideRunnerTargetResolution:
    def test_no_target_kind_errors(self, tmp_path, monkeypatch, capsys):
        _session(tmp_path, monkeypatch, workspace="test")
        with pytest.raises(SystemExit) as exc:
            DecideRunner().run("abc123", "text")
        assert exc.value.code == 2
        assert "no project/repository target configured" in capsys.readouterr().out

    def test_repository_only_session_errors(self, tmp_path, monkeypatch, capsys):
        root = tmp_path / "research"
        repo = root / "repositories" / "myrepo"
        repo.mkdir(parents=True)
        (repo / "myrepo.yaml").write_text(
            "schema_version: 1\nkind: repository\nid: myrepo\n"
            "main: memory.md\ncheckout: /tmp/myrepo\n",
        )
        (repo / "memory.md").write_text("# Architecture\n\nFacts.\n")
        monkeypatch.setattr(
            "owrap.utils.memory.records.get_workspace_config",
            lambda workspace: {"docs_root": str(root)},
        )
        _session(
            tmp_path, monkeypatch,
            target_kind="repository", repository_id="myrepo", workspace="test",
        )
        with pytest.raises(SystemExit) as exc:
            DecideRunner().run("abc123", "text")
        assert exc.value.code == 2
        assert "repository-only sessions have no project decisions" in (
            capsys.readouterr().out
        )
