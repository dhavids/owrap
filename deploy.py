#!/usr/bin/env python3
"""
Promote a filtered development snapshot into the live main checkout.
"""

import argparse
import hashlib
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


DEV_BRANCH = "dev"
LIVE_BRANCH = "main"


def git(repo: Path, *args: str, check: bool = True) -> str:
    """
    Run Git in a repository and return stripped standard output.
    """
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(message)
    return result.stdout.strip()


def validate_source(source: Path) -> str:
    """
    Validate the development checkout and return its commit.
    """
    if git(source, "branch", "--show-current") != DEV_BRANCH:
        raise RuntimeError(f"development checkout must be on {DEV_BRANCH}")
    if git(source, "status", "--porcelain"):
        raise RuntimeError("development checkout has uncommitted changes")
    attributes = git(source, "show", "HEAD:.gitattributes")
    required = {"/tests", "/pytest.ini", "/deploy.py", "/files"}
    excluded = {
        line.split()[0]
        for line in attributes.splitlines()
        if line.endswith(" export-ignore")
    }
    missing = sorted(required - excluded)
    if missing:
        raise RuntimeError(
            f"release exclusions missing: {', '.join(missing)}"
        )
    return git(source, "rev-parse", "HEAD")


def validate_target(target: Path, apply: bool) -> None:
    """
    Validate the live checkout and select its main branch when applying.
    """
    if not (target / ".git").exists():
        raise RuntimeError(f"live checkout is not a Git repository: {target}")
    if git(target, "status", "--porcelain"):
        raise RuntimeError("live checkout has uncommitted changes")
    branch = git(target, "branch", "--show-current")
    if branch == LIVE_BRANCH or not apply:
        return
    local_main = git(target, "branch", "--list", LIVE_BRANCH)
    if local_main:
        git(target, "switch", LIVE_BRANCH)
        return
    if branch == "live":
        remote_main = git(target, "branch", "--remotes", "--list", "*/main")
        if remote_main:
            remote = remote_main.splitlines()[0].strip()
            result = subprocess.run(
                [
                    "git", "-C", str(target), "merge-base",
                    "--is-ancestor", remote, "HEAD",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode:
                raise RuntimeError(
                    f"{remote} is not an ancestor of the live branch"
                )
        git(target, "switch", "-c", LIVE_BRANCH)
        return
    remote_main = git(target, "branch", "--remotes", "--list", "*/main")
    if not remote_main:
        raise RuntimeError("live repository has no main branch")
    remote = remote_main.splitlines()[0].strip().removesuffix("/main")
    git(target, "switch", "--track", f"{remote}/main")


def strip_dev_sections(readme: Path) -> None:
    """
    Remove every top-level `## ...-Dev` section from a promoted README.
    """
    if not readme.is_file():
        return
    text = readme.read_text()
    parts = re.split(r"(?m)^(?=## )", text)
    kept = [parts[0]]
    for part in parts[1:]:
        if part.splitlines()[0].rstrip().lower().endswith("-dev"):
            continue
        kept.append(part)
    readme.write_text("".join(kept).rstrip() + "\n")


def build_release(source: Path, commit: str, destination: Path) -> None:
    """
    Extract Git's export filtered tree for a development commit, with the
    promoted README's dev-only section stripped.
    """
    archive_path = destination.parent / "release.tar"
    with archive_path.open("wb") as archive_file:
        result = subprocess.run(
            [
                "git", "-C", str(source), "archive",
                "--format=tar", commit,
            ],
            check=False,
            stdout=archive_file,
            stderr=subprocess.PIPE,
        )
    if result.returncode:
        raise RuntimeError(result.stderr.decode().strip())
    destination.mkdir(parents=True)
    with tarfile.open(archive_path) as archive:
        root = destination.resolve()
        for member in archive.getmembers():
            path = (destination / member.name).resolve()
            if not path.is_relative_to(root):
                raise RuntimeError(f"unsafe archive path: {member.name}")
        archive.extractall(destination)
    strip_dev_sections(destination / "README.md")


def manifest(root: Path) -> dict[str, tuple[int, str]]:
    """
    Return file modes and content hashes for a tree, excluding Git data.
    """
    entries = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] == ".git":
            continue
        if path.is_symlink():
            content = str(path.readlink()).encode()
        elif path.is_file():
            content = path.read_bytes()
        else:
            continue
        mode = stat.S_IMODE(path.lstat().st_mode)
        entries[str(relative)] = (mode, hashlib.sha256(content).hexdigest())
    return entries


def changes(release: Path, target: Path) -> list[str]:
    """
    Describe file changes needed to make the target match the release.
    """
    wanted = manifest(release)
    current = manifest(target)
    result = []
    for path in sorted(wanted.keys() - current.keys()):
        result.append(f"add     {path}")
    for path in sorted(current.keys() - wanted.keys()):
        result.append(f"delete  {path}")
    for path in sorted(wanted.keys() & current.keys()):
        if wanted[path] != current[path]:
            result.append(f"update  {path}")
    return result


def replace_tree(release: Path, target: Path) -> None:
    """
    Replace live working files with the filtered release tree.
    """
    for path in target.iterdir():
        if path.name == ".git":
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    for path in release.iterdir():
        destination = target / path.name
        if path.is_dir() and not path.is_symlink():
            shutil.copytree(path, destination, symlinks=True)
        elif path.is_symlink():
            destination.symlink_to(path.readlink())
        else:
            shutil.copy2(path, destination)


def promote(
    source: Path,
    target: Path,
    apply: bool = False,
    install: bool = True,
    push: bool = False,
) -> int:
    """
    Preview or apply one filtered development promotion.
    """
    if push and not apply:
        raise RuntimeError("--push requires --apply")
    commit = validate_source(source)
    validate_target(target, apply)
    with tempfile.TemporaryDirectory(prefix="owrap-release-") as temp:
        release = Path(temp) / "release"
        build_release(source, commit, release)
        pending = changes(release, target)
        print(f"source: {commit}")
        print(f"target: {target}")
        print(f"branch: {LIVE_BRANCH}")
        if not pending:
            print("No release file changes.")
            return 0
        for line in pending:
            print(line)
        if not apply:
            print("Preview only. Run with --apply to promote.")
            return 0
        replace_tree(release, target)

    git(target, "add", "--all")
    short_commit = commit[:12]
    git(
        target,
        "fetch",
        "--no-tags",
        str(source),
        f"{DEV_BRANCH}:refs/remotes/owrap-dev/{DEV_BRANCH}",
    )
    fetched = git(target, "rev-parse", f"refs/remotes/owrap-dev/{DEV_BRANCH}")
    if fetched != commit:
        raise RuntimeError("fetched dev commit does not match release source")
    tree = git(target, "write-tree")
    main_commit = git(target, "rev-parse", "HEAD")
    result = subprocess.run(
        [
            "git", "-C", str(target), "commit-tree", tree,
            "-p", main_commit, "-p", commit,
            "-m", f"Promote dev {short_commit}",
            "-m", f"Source-commit: {commit}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    git(target, "reset", "--hard", result.stdout.strip())
    if install:
        subprocess.run(
            [sys.executable, str(target / "update.py")],
            cwd=target,
            check=True,
        )
        owrap_bin = str(Path.home() / "bin" / "owrap")
        subprocess.run([owrap_bin, "sync"], check=True)
        # Kill the daemon so it reloads promoted code; self-heals on
        # the next daemon-dependent command (owrap stat here).
        subprocess.run(["pkill", "-f", "owrap.runner daemon"], check=False)
        subprocess.run([owrap_bin, "stat"], check=True, stdout=subprocess.DEVNULL)
    if push:
        git(target, "push", "origin", LIVE_BRANCH)
    print(f"Promoted {short_commit} to {target} on {LIVE_BRANCH}.")
    return 0


def parse_args() -> argparse.Namespace:
    """
    Parse deployment command arguments.
    """
    source = Path(__file__).resolve().parent
    workspace = source.parent.parent
    parser = argparse.ArgumentParser(
        description="Promote a filtered owrap dev commit to live main."
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=workspace / source.name,
        help="Live owrap checkout",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the previewed promotion",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Do not refresh live command launchers",
    )
    parser.add_argument(
        "--push",
        action="store_true",
        help="Push the resulting live main commit to its origin",
    )
    return parser.parse_args()


def main() -> int:
    """
    Run the deployment command.
    """
    args = parse_args()
    source = Path(__file__).resolve().parent
    try:
        return promote(
            source,
            args.target.resolve(),
            apply=args.apply,
            install=not args.skip_install,
            push=args.push,
        )
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"deploy: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
