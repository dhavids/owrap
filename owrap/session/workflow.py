import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from ..utils.filelock import file_lock
from ..utils.checkout import is_development, live_checkout
from ..utils.memory.records import _record, docs_root, session_repositories
from ..utils.parser.sections import extract_section, merge_log_entries
from ..utils.paths import OWRAP_ROOT, context_path, get_workspace_config, _read_config
from ..utils.session.resolver import (
    _parse, _write, attach, mint_session_id, resolve, session_file,
)


def _git(checkout: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(checkout), *args],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise ValueError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def _workspace(data: dict) -> Path:
    name = data.get("workspace") or _read_config().get("default_workspace", "")
    value = get_workspace_config(name).get("workspace", "")
    path = Path(value)
    if not value or not path.is_absolute() or not path.is_dir():
        raise ValueError(f"workspace is not an existing absolute directory: {value}")
    return path.resolve()


def _repository_checkout(repo_id: str, workspace: str) -> Path:
    root = docs_root(workspace)
    path = root / "repositories" / repo_id / f"{repo_id}.yaml"
    record = _record(path, "repository", repo_id)
    checkout = Path(record.get("checkout", ""))
    if not checkout.is_absolute() or not checkout.is_dir():
        raise ValueError(f"invalid checkout for repository {repo_id}")
    checkout = checkout.resolve()
    _reject_live_checkout(checkout)
    if Path(_git(checkout, "rev-parse", "--show-toplevel")) != checkout:
        raise ValueError(f"checkout must be a Git worktree root: {checkout}")
    return checkout


def _reject_live_checkout(checkout: Path):
    if (
        is_development(OWRAP_ROOT)
        and checkout.resolve().is_relative_to(live_checkout(OWRAP_ROOT))
    ):
        raise ValueError("development branch sessions cannot edit live owrap")


def _context_entries(text: str, heading: str) -> list[str]:
    section = extract_section(text, heading)
    if not section:
        return []
    return [line for line in section.splitlines()[1:] if line.strip()]


def _write_atomic(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
        if path.exists():
            os.chmod(name, path.stat().st_mode)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _create_context(sid: str, mode: str, name: str):
    path = context_path(sid)
    content = (
        f"## Session\n\nsession: {sid}\nmode: {mode}\nname: {name}\n\n"
        "## Focus\n\n## Active Plan\n\n## Key Locations\n\n"
        "## Decisions\n\n## Environment\n\n## How To\n\n"
        "## Frequent Files\n\n## Recent\n"
    )
    _write_atomic(path, content)


class SessionWorkflow:
    """
    Create, reconcile, and merge temporary and inherited sessions.
    """

    def create(self, mode: str, label: str = "", ref: str = "") -> dict:
        """
        Create a session and optional Git worktrees under its workspace.
        """
        if mode not in ("spawn", "branch", "temp"):
            raise ValueError(f"unknown session mode: {mode}")
        parent_sid = None
        parent = {}
        if mode != "temp":
            parent_sid, parent_path, _ = resolve(mode="refresh")
            if not parent_sid:
                raise ValueError("no active parent session")
            parent = _parse(parent_path)
            if parent.get("collapsed_into"):
                raise ValueError("parent session is already collapsed")
        elif ref:
            raise ValueError("temp sessions cannot name a Git ref")

        sid = mint_session_id()
        display = label or f"{mode}-{sid}"
        if "\n" in display or "\r" in display or "=" in display:
            raise ValueError("session name cannot contain newlines or '='")
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        data = {
            "session_id": sid, "session_mode": mode, "session_name": display,
            "started": now,
        }
        if parent_sid:
            data["parent_session_id"] = parent_sid
            for field in (
                "workspace", "target_kind", "project_id", "subproject_id",
                "repository_id", "repositories",
            ):
                if parent.get(field):
                    data[field] = parent[field]
        else:
            data["workspace"] = _read_config().get("default_workspace", "")

        worktrees = {}
        created = []
        if mode == "branch":
            repo_ids = session_repositories(parent)
            if not repo_ids:
                raise ValueError("branch session needs an associated repository")
            workspace = _workspace(data)
            branch_dir = workspace / "branches" / sid
            for repo_id in repo_ids:
                checkout = _repository_checkout(repo_id, data["workspace"])
                if _git(checkout, "status", "--porcelain"):
                    raise ValueError(f"repository has uncommitted changes: {checkout}")
                base_ref = _git(checkout, "symbolic-ref", "--quiet", "--short", "HEAD")
                branch_ref = (
                    f"{ref}/{repo_id}" if ref and len(repo_ids) > 1
                    else ref or f"owrap/{sid}/{repo_id}"
                )
                _git(checkout, "check-ref-format", "--branch", branch_ref)
                if subprocess.run(
                    ["git", "-C", str(checkout), "show-ref", "--verify",
                     "--quiet", f"refs/heads/{branch_ref}"],
                    check=False,
                ).returncode == 0:
                    raise ValueError(f"branch ref already exists: {branch_ref}")
                worktrees[repo_id] = {
                    "checkout": str(checkout),
                    "path": str(branch_dir / repo_id),
                    "ref": branch_ref,
                    "base_ref": base_ref,
                    "base_commit": _git(checkout, "rev-parse", "HEAD"),
                }
            try:
                for entry in worktrees.values():
                    path = Path(entry["path"])
                    path.parent.mkdir(parents=True, exist_ok=True)
                    _git(Path(entry["checkout"]), "worktree", "add", "-b",
                         entry["ref"], str(path), entry["base_commit"])
                    created.append(entry)
            except Exception:
                for entry in reversed(created):
                    _git(Path(entry["checkout"]), "worktree", "remove",
                         entry["path"])
                    _git(Path(entry["checkout"]), "branch", "-d", entry["ref"])
                raise
            data["branch_worktrees"] = json.dumps(worktrees, separators=(",", ":"))

        try:
            sf = session_file(sid)
            if sf.exists():
                raise FileExistsError(f"session already exists: {sid}")
            _write(sf, data)
            _create_context(sid, mode, display)
            attach(sid)
        except Exception:
            session_file(sid).unlink(missing_ok=True)
            context_path(sid).unlink(missing_ok=True)
            for entry in reversed(created):
                _git(Path(entry["checkout"]), "worktree", "remove", entry["path"])
                _git(Path(entry["checkout"]), "branch", "-d", entry["ref"])
            raise
        return data

    def collapse(self, sid: str = "", apply: bool = False) -> dict:
        """
        Preview or reconcile a child session's context with its parent.
        """
        if not sid:
            sid, _, _ = resolve(mode="refresh")
        child_path = session_file(sid)
        if not child_path.is_file():
            raise FileNotFoundError(f"session not found: {sid}")
        child = _parse(child_path)
        parent_sid = child.get("parent_session_id", "")
        if not parent_sid:
            raise ValueError("session has no parent to collapse into")
        if child.get("collapsed_into"):
            raise ValueError("session is already collapsed")
        if child.get("session_mode") == "branch" and not child.get("git_merged"):
            raise ValueError("merge branch code before collapsing this session")
        parent_path = session_file(parent_sid)
        if not parent_path.is_file():
            raise FileNotFoundError(f"parent session not found: {parent_sid}")
        child_context = context_path(sid)
        parent_context = context_path(parent_sid)
        source = child_context.read_text() if child_context.is_file() else ""
        preview = {"child": sid, "parent": parent_sid, "entries": {},
                   "applied": False}
        with file_lock(parent_context.with_suffix(".md.lock")):
            target = parent_context.read_text() if parent_context.is_file() else ""
            merged = target
            for heading in ("## Key Locations", "## Decisions", "## How To"):
                incoming = _context_entries(source, heading)
                existing = set(_context_entries(merged, heading))
                additions = [line for line in incoming if line not in existing]
                preview["entries"][heading] = additions
                if additions:
                    merged = merge_log_entries(merged, heading, additions)
            if apply:
                _write_atomic(parent_context, merged)
                child["collapsed_into"] = parent_sid
                child["collapsed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                _write(child_path, child)
                preview["applied"] = True
        return preview

    def merge_branch(
        self, sid: str = "", apply: bool = False, repo_id: str = "",
    ) -> dict:
        """
        Preview or merge a branch session's worktree refs into parent checkouts.
        """
        if not sid:
            sid, _, _ = resolve(mode="refresh")
        child = _parse(session_file(sid))
        if child.get("session_mode") != "branch":
            raise ValueError("session is not a branch session")
        worktrees = json.loads(child.get("branch_worktrees", "{}"))
        if not worktrees:
            raise ValueError("branch session has no worktrees")
        if repo_id and repo_id not in worktrees:
            raise ValueError(f"repository is not in branch session: {repo_id}")
        if apply and len(worktrees) > 1 and not repo_id:
            raise ValueError("choose --repo when merging a multi-repository branch")
        merged_ids = set(json.loads(child.get("git_merged_repositories", "[]")))
        selected = {
            name: entry for name, entry in worktrees.items()
            if (not repo_id or name == repo_id) and name not in merged_ids
        }
        if not selected:
            raise ValueError("selected branch code was already merged")
        for name, entry in selected.items():
            checkout = Path(entry["checkout"])
            _reject_live_checkout(checkout)
            if _git(checkout, "symbolic-ref", "--quiet", "--short", "HEAD") != (
                entry["base_ref"]
            ):
                raise ValueError(f"parent branch changed for {name}")
            if _git(checkout, "status", "--porcelain"):
                raise ValueError(f"parent checkout has uncommitted changes: {name}")
            if _git(Path(entry["path"]), "status", "--porcelain"):
                raise ValueError(f"branch worktree has uncommitted changes: {name}")
            _git(checkout, "merge-base", "--is-ancestor",
                 entry["base_commit"], "HEAD")
        preview = {"session": sid, "repositories": selected, "applied": False}
        for entry in selected.values():
            checkout = Path(entry["checkout"])
            entry["commits"] = _git(
                checkout, "log", "--oneline",
                f"{entry['base_ref']}..{entry['ref']}",
            )
            entry["stat"] = _git(
                checkout, "diff", "--stat",
                f"{entry['base_ref']}...{entry['ref']}",
            )
        if apply:
            for name, entry in selected.items():
                _git(Path(entry["checkout"]), "merge", "--no-ff", "--no-edit",
                     entry["ref"])
                merged_ids.add(name)
                child["git_merged_repositories"] = json.dumps(sorted(merged_ids))
                child["git_merged"] = (
                    "1" if len(merged_ids) == len(worktrees) else ""
                )
                _write(session_file(sid), child)
            preview["applied"] = True
        return preview

    def cleanup_branch(self, sid: str = "", apply: bool = False) -> dict:
        """
        Remove merged branch worktrees after their session has collapsed.
        """
        if not sid:
            sid, _, _ = resolve(mode="refresh")
        path = session_file(sid)
        child = _parse(path)
        if child.get("session_mode") != "branch":
            raise ValueError("session is not a branch session")
        if not child.get("git_merged") or not child.get("collapsed_into"):
            raise ValueError("merge code and collapse the session before cleanup")
        worktrees = json.loads(child.get("branch_worktrees", "{}"))
        cleaned = set(json.loads(child.get("cleaned_repositories", "[]")))
        pending = {name: entry for name, entry in worktrees.items()
                   if name not in cleaned}
        if not pending:
            raise ValueError("branch worktrees are already cleaned")
        workspace = _workspace(child)
        root = workspace / "branches" / sid
        extras = {item.name for item in root.iterdir()} - set(pending)
        if extras:
            raise ValueError(
                "branch folder contains other files: " + ", ".join(sorted(extras))
            )
        for name, entry in pending.items():
            checkout = Path(entry["checkout"])
            _reject_live_checkout(checkout)
            worktree = Path(entry["path"])
            if worktree.parent != root:
                raise ValueError(f"worktree is outside session branch folder: {name}")
            if _git(worktree, "status", "--porcelain"):
                raise ValueError(f"branch worktree has uncommitted changes: {name}")
            _git(checkout, "merge-base", "--is-ancestor",
                 entry["ref"], entry["base_ref"])
        result = {"session": sid, "repositories": pending, "applied": False}
        if apply:
            for name, entry in pending.items():
                checkout = Path(entry["checkout"])
                _git(checkout, "worktree", "remove", entry["path"])
                _git(checkout, "branch", "-d", entry["ref"])
                cleaned.add(name)
                child["cleaned_repositories"] = json.dumps(sorted(cleaned))
                _write(path, child)
            root.rmdir()
            result["applied"] = True
        return result
