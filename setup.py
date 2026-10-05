#!/usr/bin/env python3
"""
Install owrap command launchers for the current checkout.
"""

import shutil
import sys
from pathlib import Path

from update import SHIMS, install_shims, is_development, runtime_ready


def main() -> int:
    """
    Check the Python dependency and install command launchers.
    """
    if not runtime_ready():
        return 1

    root = Path(__file__).resolve().parent
    destination = install_shims(root, sys.executable, Path.home())
    print(f"Installed {len(SHIMS)} launchers in {destination}")
    if shutil.which("opencode") is None:
        print("opencode is unavailable; runner commands need it on PATH.")
    if is_development(root):
        print(f"Development runtime: {root / 'files' / 'state'}")
    else:
        print("Ensure ~/bin is on PATH.")
    workspace_hint = (
        root / "files" / "workspace"
        if is_development(root) else Path("<workspace-path>")
    )
    print(f"Next: {destination / 'owrap'} setup {workspace_hint}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
