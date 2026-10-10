import json

from . import Run
from ...session.workflow import SessionWorkflow


class Worktree(Run):
    """
    A branch session: a child session paired with a real Git
    worktree per repository linked to its parent, on a new branch.
    `add` creates one, `done` merges its commits back into the
    parent checkouts, `clear` removes the worktrees once merged or
    abandoned.
    """

    kind = "worktree"

    usage = {
        "add": {
            "usage": "[<name>] [<ref>]",
            "args": [
                ("name", "label for the new branch session; also used to "
                         "derive the Git branch name if ref is omitted"),
                ("ref", "Git branch ref to create; defaults to "
                        "owrap/<session_id>/<repo_id>"),
            ],
            "examples": ["", "feature-x", "feature-x feature/x"],
            "purpose": "Create a child session with Git worktrees",
            "group": "session",
        },
        "done": {
            "usage": "[<sid>] [<repo_id>] [apply]",
            "args": [
                ("sid", "branch session id; defaults to the attached session"),
                ("repo_id", "merge only this repository (required if the "
                            "branch session spans more than one)"),
                ("apply", "reserved keyword -- without it, preview only"),
            ],
            "examples": ["", "abc123 myrepo apply"],
            "purpose": "Preview or merge branch code",
            "group": "session",
        },
        "clear": {
            "usage": "[<sid>] [apply]",
            "args": [
                ("sid", "branch session id; defaults to the attached session"),
                ("apply", "reserved keyword -- without it, preview only"),
            ],
            "examples": ["", "abc123 apply"],
            "purpose": "Remove merged branch worktrees",
            "group": "session",
        },
    }


    # Public Methods

    def add(self, name: str = None, ref: str = None) -> None:
        """
        Mint a branch session and a real Git worktree, on a new
        branch, per repository linked to the parent session.
        """
        try:
            data = SessionWorkflow().create("branch", name or "", ref or "")
        except (ValueError, FileNotFoundError) as exc:
            self._fail(exc)
        print(f"Branch session: {data['session_id']} ({data['session_name']})")
        for repo_id, entry in json.loads(data["branch_worktrees"]).items():
            print(f"{repo_id}: {entry['path']} [{entry['ref']}]")
        print(f"__OWRAP_EXPORT__ SESSION_ID={data['session_id']}")

    def done(self, sid: str = None, repo_id: str = None, apply: str = None) -> None:
        """
        Merge a branch session's Git worktree refs into its parent
        checkouts -- preview only unless `apply` is given.
        """
        try:
            result = SessionWorkflow().merge_branch(
                sid or "", apply == "apply", repo_id or "",
            )
        except (ValueError, FileNotFoundError) as exc:
            self._fail(exc)
        except TypeError:
            self._fail(self.target_messages["no_target"])
        for repo, entry in result["repositories"].items():
            print(f"{repo}: {entry['ref']} -> {entry['base_ref']}")
            if entry["commits"]:
                print(entry["commits"])
            if entry["stat"]:
                print(entry["stat"])
        print("Git merge applied." if result["applied"] else
              "Preview only. Pass 'apply' to merge code.")

    def clear(self, sid: str = None, apply: str = None) -> None:
        """
        Remove a merged (or abandoned) branch session's Git
        worktrees -- preview only unless `apply` is given.
        """
        try:
            result = SessionWorkflow().cleanup_branch(sid or "", apply == "apply")
        except (ValueError, FileNotFoundError) as exc:
            self._fail(exc)
        except TypeError:
            self._fail(self.target_messages["no_target"])
        for entry in result["repositories"].values():
            print(f"Worktree: {entry['path']}")
        print("Worktrees removed." if result["applied"] else
              "Preview only. Pass 'apply' to remove worktrees.")
