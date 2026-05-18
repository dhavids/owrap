#!/usr/bin/env python3
"""owrap update — re-installs shims to ~/bin/ after git pull.

Python source takes effect immediately (editable install).
Only the shims in ~/bin/ need re-writing when bin/ templates change.
"""

import stat
import sys
from pathlib import Path

from owrap.utils.paths import OWRAP_ROOT

SHIMS = ("orun", "oexec", "oread", "owait", "owrap")


def main():
    python_exe = sys.executable
    bin_src = OWRAP_ROOT / "bin"
    bin_dst = Path.home() / "bin"
    bin_dst.mkdir(parents=True, exist_ok=True)

    print("=== owrap update ===\n")

    for name in SHIMS:
        src = bin_src / name
        if not src.exists():
            print(f"  error: template {src} not found — run from the owrap repo root")
            sys.exit(1)
        content = (src.read_text()
                   .replace("<OWRAP_ROOT>", str(OWRAP_ROOT))
                   .replace("<PYTHON>", python_exe))
        dst = bin_dst / name
        dst.write_text(content)
        dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        print(f"  updated  {dst}")

    print()
    print("Shims updated.")
    print("Python source is live immediately (editable install — no reinstall needed).")
    print("Running server uses source files directly — no restart needed.")


if __name__ == "__main__":
    main()
