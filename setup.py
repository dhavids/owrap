#!/usr/bin/env python3
"""owrap setup — checks deps, installs shims to ~/bin/."""

import os
import shutil
import stat
import sys
from pathlib import Path

from owrap.utils.paths import OWRAP_ROOT


class SetupRunner:
    """Configure owrap for a research project."""

    def run(self):
        fatal = False

        # Python version check
        if sys.version_info < (3, 10):
            print(f"Error: Python 3.10+ required (found {sys.version.split()[0]})")
            sys.exit(1)

        # Check opencode
        if shutil.which("opencode") is None:
            print("WARNING: opencode CLI not found. Install opencode before using owrap.")
            print("  See opencode documentation for installation instructions.")
            fatal = True

        # Check inotifywait
        if shutil.which("inotifywait") is None:
            print("WARNING: inotifywait not found. Install inotify-tools:")
            print("  sudo apt install inotify-tools")
            fatal = True

        # Install shims
        bin_src = OWRAP_ROOT / "bin"
        bin_dst = Path.home() / "bin"
        bin_dst.mkdir(parents=True, exist_ok=True)

        for name in ("orun", "oexec", "oread", "owait", "owrap"):
            src = bin_src / name
            if not src.exists():
                print(f"Error: shim source {src} not found")
                sys.exit(1)
            content = src.read_text().replace("<OWRAP_ROOT>", str(OWRAP_ROOT))
            dst = bin_dst / name
            dst.write_text(content)
            dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            print(f"  installed {dst}")

        # Check ~/bin in PATH
        if str(bin_dst) not in os.environ.get("PATH", ""):
            print(f"WARNING: {bin_dst} is not in your PATH.")
            print('  Add this to your shell rc (e.g. ~/.bashrc):')
            print(f'  export PATH="$HOME/bin:$PATH"')

        if fatal:
            print("\nSetup completed with warnings. Install missing dependencies before use.")
        else:
            print("\nSetup complete.")
        sys.exit(0)


def main():
    SetupRunner().run()


if __name__ == "__main__":
    main()
