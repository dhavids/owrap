import importlib.util
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("deploy_script", ROOT / "deploy.py")
deploy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy)


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repository(path):
    path.mkdir()
    _git(path, "init", "-b", "dev")
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "user.email", "test@example.com")
    (path / ".gitattributes").write_text(
        "/tests export-ignore\n"
        "/pytest.ini export-ignore\n"
        "/deploy.py export-ignore\n"
        "/files export-ignore\n"
    )
    (path / ".gitignore").write_text("__pycache__/\n")
    (path / "app.py").write_text("print('live')\n")
    (path / "deploy.py").write_text("dev only\n")
    (path / "pytest.ini").write_text("[pytest]\n")
    (path / "tests").mkdir()
    (path / "tests" / "test_app.py").write_text("def test_app(): pass\n")
    (path / "files").mkdir()
    (path / "files" / "state").write_text("private\n")
    _git(path, "add", "--all")
    _git(path, "commit", "-m", "development")


def test_build_release_omits_development_files(tmp_path):
    source = tmp_path / "source"
    release = tmp_path / "release"
    _repository(source)

    deploy.build_release(source, _git(source, "rev-parse", "HEAD"), release)

    assert (release / "app.py").is_file()
    assert (release / ".gitattributes").is_file()
    assert (release / ".gitignore").is_file()
    assert not (release / "tests").exists()
    assert not (release / "pytest.ini").exists()
    assert not (release / "deploy.py").exists()
    assert not (release / "files").exists()


def test_changes_reports_release_delta(tmp_path):
    release = tmp_path / "release"
    target = tmp_path / "target"
    release.mkdir()
    target.mkdir()
    (release / "add.py").write_text("new\n")
    (release / "same.py").write_text("new\n")
    (target / "same.py").write_text("old\n")
    (target / "delete.py").write_text("old\n")

    assert deploy.changes(release, target) == [
        "add     add.py",
        "delete  delete.py",
        "update  same.py",
    ]


def test_promote_commits_filtered_snapshot_to_separate_main_repo(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    _repository(source)
    target.mkdir()
    _git(target, "init", "-b", "main")
    _git(target, "config", "user.name", "Test")
    _git(target, "config", "user.email", "test@example.com")
    (target / "old.py").write_text("old\n")
    _git(target, "add", "--all")
    _git(target, "commit", "-m", "live")

    assert deploy.promote(
        source,
        target,
        apply=True,
        install=False,
    ) == 0

    assert _git(target, "branch", "--show-current") == "main"
    assert (target / "app.py").is_file()
    assert not (target / "old.py").exists()
    assert not (target / "tests").exists()
    assert not (target / "pytest.ini").exists()
    assert not (target / "deploy.py").exists()
    parents = _git(target, "show", "-s", "--format=%P", "HEAD").split()
    assert len(parents) == 2
    source_commit = _git(source, "rev-parse", "HEAD")
    assert parents[1] == source_commit


def test_validate_target_preserves_first_live_snapshot(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    _git(target, "init", "-b", "live")
    _git(target, "config", "user.name", "Test")
    _git(target, "config", "user.email", "test@example.com")
    (target / "app.py").write_text("print('live')\n")
    _git(target, "add", "--all")
    _git(target, "commit", "-m", "live snapshot")
    live_commit = _git(target, "rev-parse", "HEAD")

    deploy.validate_target(target, apply=True)

    assert _git(target, "branch", "--show-current") == "main"
    assert _git(target, "rev-parse", "HEAD") == live_commit
    assert _git(target, "rev-parse", "live") == live_commit
