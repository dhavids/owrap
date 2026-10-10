import json

import pytest


@pytest.fixture
def setup_env(tmp_path, monkeypatch):
    from owrap_old.commands import setup as setup_module

    dev_root = tmp_path / "dev" / "owrap"
    dev_files = dev_root / "files"
    workspace = dev_files / "workspace"
    workspace.mkdir(parents=True)
    state = dev_files / "state"
    configs = state / "configs"

    monkeypatch.setattr(setup_module, "OWRAP_ROOT", dev_root)
    monkeypatch.setattr(setup_module, "OWRAP_HOME", state)
    monkeypatch.setattr(setup_module, "FALLBACK_DIR", state / "sessions" / "f")
    monkeypatch.setattr(setup_module, "CONFIGS_DIR", configs)
    monkeypatch.setattr(setup_module, "BASE_CONFIG_FILE", configs / "base.json")
    monkeypatch.setattr(
        setup_module, "project_config_path",
        lambda name: configs / f"{name}.json",
    )
    monkeypatch.setattr(setup_module, "discover_free_model", lambda: None)
    staged = []
    monkeypatch.setattr(setup_module, "stage_all", staged.append)
    return setup_module, workspace, configs, staged


def test_setup_uses_name_override_and_preserves_workspace_files(
    setup_env, capsys,
):
    setup_module, workspace, configs, staged = setup_env
    planner = workspace / "planner.md"
    executor = workspace / "executor.md"
    planner.write_text("user planner\n")
    executor.write_text("user executor\n")

    with pytest.raises(SystemExit) as result:
        setup_module.SetupRunner().run(path=workspace, project_name="chosen")

    assert result.value.code == 0
    config = json.loads((configs / "chosen.json").read_text())
    assert config["workspace"] == str(workspace)
    assert config["docs_root"] == str(workspace / "docs" / "research")
    base = json.loads((configs / "base.json").read_text())
    assert base["bin_dir"] == str(workspace.parents[1] / "files" / "bin")
    assert staged == ["chosen"]
    assert planner.read_text() == "user planner\n"
    assert executor.read_text() == "user executor\n"
    assert "then run `owrap sync`" in capsys.readouterr().out


def test_dev_setup_rejects_workspace_outside_files(setup_env, tmp_path):
    setup_module, _, configs, staged = setup_env
    outside = tmp_path / "live"
    outside.mkdir()

    with pytest.raises(SystemExit) as result:
        setup_module.SetupRunner().run(path=outside)

    assert result.value.code == 1
    assert not configs.exists()
    assert staged == []


def test_dev_setup_rejects_existing_external_memory_root(setup_env, tmp_path):
    setup_module, workspace, configs, staged = setup_env
    configs.mkdir(parents=True)
    external = tmp_path / "live-memory"
    (configs / "workspace.json").write_text(json.dumps({
        "docs_root": str(external),
    }))

    with pytest.raises(SystemExit) as result:
        setup_module.SetupRunner().run(path=workspace)

    assert result.value.code == 1
    assert not (configs / "base.json").exists()
    assert staged == []


def test_setup_rejects_conflicting_workspace_arguments(setup_env):
    setup_module, workspace, configs, staged = setup_env

    with pytest.raises(SystemExit) as result:
        setup_module.SetupRunner().run(
            path=workspace, workspace=str(workspace),
        )

    assert result.value.code == 1
    assert not configs.exists()
    assert staged == []


def test_setup_explicit_flags_override_existing_config(setup_env):
    setup_module, workspace, configs, _ = setup_env
    configs.mkdir(parents=True)
    (configs / "workspace.json").write_text(json.dumps({
        "runner_allow_all": False,
        "runner_use_oread": True,
    }))

    with pytest.raises(SystemExit) as result:
        setup_module.SetupRunner().run(
            path=workspace, allow_all=True, oread=False,
        )

    assert result.value.code == 0
    config = json.loads((configs / "workspace.json").read_text())
    assert config["runner_allow_all"] is True
    assert config["runner_use_oread"] is False


def test_setup_migrates_legacy_research_root_key(setup_env):
    setup_module, workspace, configs, _ = setup_env
    configs.mkdir(parents=True)
    # Not the default docs/research path — a pass proves migration, not a lucky default.
    legacy_root = workspace / "custom" / "docs-location"
    legacy_root.mkdir(parents=True)
    (configs / "workspace.json").write_text(json.dumps({
        "research_root": str(legacy_root),
    }))

    with pytest.raises(SystemExit) as result:
        setup_module.SetupRunner().run(path=workspace)

    assert result.value.code == 0
    config = json.loads((configs / "workspace.json").read_text())
    assert config["docs_root"] == str(legacy_root)
    assert "research_root" not in config


def test_setup_stores_role_harnesses(setup_env, capsys):
    setup_module, workspace, configs, _ = setup_env

    with pytest.raises(SystemExit) as result:
        setup_module.SetupRunner().run(
            path=workspace,
            planners=["claude", "codex"],
            executors=["claude"],
        )

    assert result.value.code == 0
    config = json.loads((configs / "workspace.json").read_text())
    assert config["role_harnesses"] == {
        "planner": ["claude", "codex"],
        "executor": ["claude"],
    }
    assert "executor content merged into CLAUDE.md" in capsys.readouterr().out
