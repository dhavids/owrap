#!/usr/bin/env python3
"""owrap setup — checks deps, installs shims to ~/bin/."""

import os
import shutil
import stat
import sys
from pathlib import Path

from owrap.utils.paths import (
    OWRAP_ROOT, _resolve_owrap_home, OWRAP_HOME_POINTER_FILE)


class SetupRunner:

    def run(self):
        print("=== owrap setup ===\n")

        # Step 1: Check dependencies
        missing = []

        if shutil.which("opencode") is None:
            missing.append(("opencode", "npm i -g opencode-ai"))

        if shutil.which("inotifywait") is None:
            missing.append(("inotifywait", "sudo apt install inotify-tools -y"))

        if missing:
            print("Missing dependencies:\n")
            for name, cmd in missing:
                print(f"  {name:<14} {cmd}")
            print("\nInstall the above and re-run: python3 setup.py")
            sys.exit(1)

        # Step 2: Python version check
        if sys.version_info < (3, 10):
            print(f"Error: Python 3.10+ required (found {sys.version.split()[0]})")
            sys.exit(1)

        # Step 3: Install shims
        python_exe = sys.executable
        bin_src = OWRAP_ROOT / "bin"
        bin_dst = Path.home() / "bin"
        bin_dst.mkdir(parents=True, exist_ok=True)

        for name in ("orun", "oexec", "oread", "owait", "owrap"):
            src = bin_src / name
            if not src.exists():
                print(f"Error: shim source {src} not found")
                sys.exit(1)
            content = (src.read_text()
                       .replace("<OWRAP_ROOT>", str(OWRAP_ROOT))
                       .replace("<PYTHON>", python_exe))
            dst = bin_dst / name
            existed = dst.exists()
            dst.write_text(content)
            dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            verb = "updated" if existed else "installed"
            print(f"  {verb} {dst}")

        # Install bash autocompletion
        auto_comp = OWRAP_ROOT / "bin" / "auto_comp.sh"
        if auto_comp.exists():
            auto_comp.chmod(0o755)
            bashrc = Path.home() / ".bashrc"
            if not bashrc.exists():
                bashrc.touch()
            target = str(auto_comp.resolve())
            content = bashrc.read_text()
            if target not in content:
                with open(bashrc, "a") as f:
                    f.write(f"# Auto-compiled completion: source {target}\n")
                    f.write(f'if [ -f "{target}" ]; then\n')
                    f.write(f'    source "{target}"\n')
                    f.write("fi\n")
                print("  installed bash autocompletion")
            else:
                print("  bash autocompletion already installed")

        resolved_home = _resolve_owrap_home()
        if OWRAP_HOME_POINTER_FILE.exists() or os.environ.get("OWRAP_HOME"):
            print(f"  Using existing OWRAP_HOME: {resolved_home}")
        else:
            resolved_home.mkdir(parents=True, exist_ok=True)
            OWRAP_HOME_POINTER_FILE.write_text(str(resolved_home))
            print(f"  Created new OWRAP_HOME: {resolved_home}")

        print("\nShims installed. Use the ~/bin/ prefix for all commands:")
        print(f"  {bin_dst}/owrap setup <research_root>")
        print(f"  {bin_dst}/owrap start <name>")

        # Step 4: PATH check
        bin_dst_str = str(bin_dst)
        check_path = True      # We allow for now so you can use the short cmd in terminal
        if bin_dst_str not in os.environ.get("PATH", "") and check_path:
            print(f"\n{bin_dst} is not in your PATH.")
            try:
                answer = input(
                    "Add it to ~/.bashrc automatically? [y/N] "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = "n"

            if answer == "y":
                rc_file = Path.home() / ".bashrc"
                with open(rc_file, "a") as f:
                    f.write('\nexport PATH="$HOME/bin:$PATH"\n')
                print(f"  Added to {rc_file}.")
                print("  Open a new terminal for the change to take effect.")
                print("  Until then, use the full path:")
                print(f"    {bin_dst_str}/owrap <command>")
            else:
                print("  To add manually:")
                print("    echo 'export PATH=\"$HOME/bin:$PATH\"' >> ~/.bashrc")
                print("    source ~/.bashrc   # or open a new terminal")
                print("  Until then, use the full path:")
                print(f"    {bin_dst_str}/owrap <command>")

        print("\nSetup complete.")
        sys.exit(0)


def main():
    SetupRunner().run()


if __name__ == "__main__":
    main()
