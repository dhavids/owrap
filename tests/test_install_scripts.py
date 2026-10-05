import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import setup as setup_script
import update as update_script
from update import SHIMS, install_shims


def _templates(root: Path) -> None:
    source_dir = root / "bin"
    source_dir.mkdir(parents=True)
    for name in SHIMS:
        (source_dir / name).write_text(
            "#!/bin/bash\n"
            "cd \"<OWRAP_ROOT>\"\n"
            "<PYTHON> -m owrap.runner\n"
        )


def test_dev_install_uses_private_bin_and_runtime(tmp_path):
    root = tmp_path / "dev" / "owrap"
    home = tmp_path / "home"
    root.parent.mkdir()
    _templates(root)

    destination = install_shims(root, "/tmp/python", home)

    assert destination == root / "files" / "bin"
    assert not (home / "bin").exists()
    assert {path.name for path in destination.iterdir()} == set(SHIMS)
    content = (destination / "owrap").read_text()
    assert f"export OWRAP_HOME={root / 'files' / 'state'}" in content
    assert "unset SESSION_ID OWRAP_SESSION" in content
    assert "CLAUDE_CODE_SESSION_ID" not in content
    assert f'cd "{root}"' in content
    assert "/tmp/python -m owrap.runner" in content
    assert (destination / "owrap").stat().st_mode & 0o111


def test_live_install_uses_shared_bin(tmp_path):
    root = tmp_path / "owrap"
    home = tmp_path / "home"
    _templates(root)

    destination = install_shims(root, "/tmp/python", home)

    assert destination == home / "bin"
    assert not (root / "files").exists()
    assert "export OWRAP_HOME=" not in (destination / "owrap").read_text()


@pytest.mark.parametrize("script_name", ("setup.py", "update.py"))
def test_live_entry_point_installs_to_user_bin(tmp_path, script_name):
    root = tmp_path / "owrap"
    home = tmp_path / "home"
    source_root = Path(__file__).resolve().parents[1]
    root.mkdir()
    home.mkdir()
    _templates(root)
    for name in ("setup.py", "update.py"):
        shutil.copy2(source_root / name, root / name)

    env = os.environ.copy()
    env["HOME"] = str(home)
    result = subprocess.run(
        [sys.executable, str(root / script_name)],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=False,
    )

    assert result.returncode == 0, result.stderr
    destination = home / "bin"
    assert {path.name for path in destination.iterdir()} == set(SHIMS)
    assert str(destination) in result.stdout
    assert not (root / "files").exists()
    for name in SHIMS:
        content = (destination / name).read_text()
        assert f'cd "{root}"' in content
        assert f"{sys.executable} -m owrap.runner" in content
        assert "export OWRAP_HOME=" not in content


def test_install_rejects_missing_template_before_writing(tmp_path):
    root = tmp_path / "dev" / "owrap"
    home = tmp_path / "home"
    root.parent.mkdir()
    _templates(root)
    (root / "bin" / "oagent").unlink()

    with pytest.raises(FileNotFoundError, match="oagent"):
        install_shims(root, "/tmp/python", home)

    assert not (root / "files" / "bin").exists()


def test_dev_install_rejects_bin_link_outside_checkout(tmp_path):
    root = tmp_path / "dev" / "owrap"
    home = tmp_path / "home"
    root.parent.mkdir()
    _templates(root)
    (root / "files").mkdir()
    (home / "bin").mkdir(parents=True)
    (root / "files" / "bin").symlink_to(home / "bin")

    with pytest.raises(ValueError, match="under files"):
        install_shims(root, "/tmp/python", home)

    assert list((home / "bin").iterdir()) == []


def test_dev_install_rejects_launcher_link_outside_checkout(tmp_path):
    root = tmp_path / "dev" / "owrap"
    home = tmp_path / "home"
    root.parent.mkdir()
    _templates(root)
    (root / "files" / "bin").mkdir(parents=True)
    (home / "bin").mkdir(parents=True)
    live_launcher = home / "bin" / "owrap"
    live_launcher.write_text("live\n")
    (root / "files" / "bin" / "owrap").symlink_to(live_launcher)

    with pytest.raises(ValueError, match="symbolic links"):
        install_shims(root, "/tmp/python", home)

    assert live_launcher.read_text() == "live\n"


def test_dev_import_rejects_external_home_before_writing(tmp_path):
    root = Path(__file__).resolve().parents[1]
    outside = tmp_path / "live-state"
    env = os.environ.copy()
    env["OWRAP_HOME"] = str(outside)

    result = subprocess.run(
        [sys.executable, "-c", "import owrap.utils.paths"],
        cwd=root, env=env, capture_output=True, text=True, check=False,
    )

    assert result.returncode != 0
    assert "Development OWRAP_HOME must be under" in result.stderr
    assert not outside.exists()


def test_release_archive_excludes_development_paths():
    root = Path(__file__).resolve().parents[1]
    attributes = (root / ".gitattributes").read_text().splitlines()

    assert set(attributes) == {
        "/tests export-ignore",
        "/pytest.ini export-ignore",
        "/deploy.py export-ignore",
        "/.pytest_cache export-ignore",
        "/files export-ignore",
    }


def test_setup_requires_yaml_before_installing(monkeypatch, capsys):
    monkeypatch.setattr(update_script.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(
        setup_script, "install_shims",
        lambda *args: pytest.fail("install started without PyYAML"),
    )

    assert setup_script.main() == 1
    assert "PyYAML is required" in capsys.readouterr().err


def test_update_requires_yaml_before_installing(monkeypatch, capsys):
    monkeypatch.setattr(update_script.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(
        update_script, "install_shims",
        lambda *args: pytest.fail("update started without PyYAML"),
    )

    assert update_script.main() == 1
    assert "PyYAML is required" in capsys.readouterr().err
