#!/usr/bin/env python3
"""
Install command launchers for the current owrap checkout.
"""

import importlib.util
import shlex
import stat
import sys
from pathlib import Path


SHIMS = ("owrap", "orun", "oexec", "oread", "owait", "oagent")


def is_development(root: Path) -> bool:
    """
    Return whether a checkout lives in the workspace development directory.
    """
    return root.resolve().parent.name == "dev"


def runtime_ready() -> bool:
    """
    Check that this Python interpreter can run owrap.
    """
    if sys.version_info < (3, 10):
        print("Python 3.10 or newer is required.", file=sys.stderr)
        return False
    if importlib.util.find_spec("yaml") is None:
        print(
            "PyYAML is required. Install it for this Python interpreter: "
            f"{sys.executable} -m pip install PyYAML",
            file=sys.stderr,
        )
        return False
    return True


def launcher_dir(root: Path, home: Path) -> Path:
    """
    Select the command directory for this checkout.
    """
    if is_development(root):
        return root / "files" / "bin"
    return home / "bin"


def install_shims(root: Path, python_exe: str, home: Path) -> Path:
    """
    Render the command launchers into the selected directory.
    """
    source_dir = root / "bin"
    missing = [name for name in SHIMS if not (source_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Missing launcher templates: {', '.join(missing)}"
        )

    destination = launcher_dir(root, home)
    if is_development(root):
        dev_files = root / "files"
        if not dev_files.resolve().is_relative_to(root.resolve()):
            raise ValueError("Development files directory leaves the checkout")
        if not destination.resolve().is_relative_to(dev_files.resolve()):
            raise ValueError("Development launchers must stay under files")
        if any((destination / name).is_symlink() for name in SHIMS):
            raise ValueError("Development launcher targets cannot be symbolic links")
    destination.mkdir(parents=True, exist_ok=True)
    for name in SHIMS:
        source = source_dir / name
        content = (
            source.read_text()
            .replace("<OWRAP_ROOT>", str(root))
            .replace("<PYTHON>", shlex.quote(python_exe))
        )
        if is_development(root):
            dev_home = shlex.quote(str(root / "files" / "state"))
            prefix = (
                f"export OWRAP_HOME={dev_home}\n"
                "unset SESSION_ID OWRAP_SESSION OWRAP_RESEARCH "
                "OWRAP_SERVER_URL\n"
            )
            content = content.replace("\n", f"\n{prefix}", 1)
        target = destination / name
        target.write_text(content)
        target.chmod(
            stat.S_IMODE(source.stat().st_mode)
            | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
    return destination


def main() -> int:
    """
    Refresh the launchers for the current checkout.
    """
    if not runtime_ready():
        return 1
    root = Path(__file__).resolve().parent
    destination = install_shims(root, sys.executable, Path.home())
    print(f"Updated {len(SHIMS)} launchers in {destination}")
    print("Restart running owrap processes to load changed Python code.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
