import os
import re
import sys
import time
from pathlib import Path

from . import Record
from ...utils.session.resolver import _parse, session_file
from ...utils.io.atomic import write_atomic
from ...utils.io.filelock import file_lock
from ...utils.memory.records import docs_root
from ...utils.paths import TEMPLATES_DIR

OWNER_PROJECT = "owrap"
REQUIRED_SECTIONS = ("## Problem", "## Suggested change")
OPEN_STATUSES = ("open", "claimed")
STEPS = ("claim", "done", "reject", "note")
OWNER_STEPS = ("claim", "done", "reject")
MATCH_OVERLAP = 0.6
STOPWORDS = frozenset(
    "a an and are as at be by for from in is it of on or the to with".split()
)


class Proposal(Record):
    """
    A change a planner wants in owrap's own tooling, filed from any
    session and worked only by the `owrap` project's session. One
    Markdown file per proposal under `<docs_root>/proposals/`: `add`
    files one (refusing a near-duplicate of an open proposal), `get`
    lists, reads, or prints the template, and `do` moves one through
    claim/done/reject (owrap session only) or appends a note (any).
    """

    kind = "proposal"

    usage = {
        "add": {
            "usage": "<file|-> [--force]",
            "args": [
                ("file", "filled-in template (`owrap get proposal template`); "
                         "'-' reads stdin"),
                ("--force", "file even if a similar open proposal exists"),
            ],
            "examples": ["proposal.md", "- --force"],
            "purpose": "File a change request for owrap's tooling",
            "group": "record",
        },
        "get": {
            "usage": "[template|all|<id>]",
            "args": [
                ("template", "print the proposal template"),
                ("all", "include done and rejected proposals"),
                ("id", "print one proposal (unambiguous prefix)"),
            ],
            "examples": ["", "template", "all", "my-proposal"],
            "purpose": "List open owrap tooling proposals, or print the template",
            "group": "record",
        },
        "do": {
            "usage": "<id> <claim|done|reject|note> [<text>]",
            "args": [
                ("id", "proposal id (unambiguous prefix)"),
                ("step", "claim/done/reject: owrap session only; "
                         "note: any session"),
                ("text", "note text, or the reason for done/reject"),
            ],
            "examples": ["my-proposal claim", 'my-proposal note "also seen in X"'],
            "purpose": "Work a proposal (owrap session) or add a note (any)",
            "group": "record",
        },
    }

    messages = {
        "add": "PROPOSAL filed: {id} ({path})",
        "get": "{text}",
        "do": "PROPOSAL {id}: {text}",
    }


    # Public Methods

    def add(self, file: str = None, force: bool = False) -> None:
        """
        File a proposal from a filled-in template, unless it matches
        an open one.
        """
        if file is None:
            self._usage("add")
        body = self._read_body(file)
        title = self._title(body)
        missing = [s for s in REQUIRED_SECTIONS if s not in body]
        if missing:
            self._fail(
                f"missing section(s): {', '.join(missing)} -- "
                "see `owrap get proposal template`"
            )
        similar = self._similar(title)
        if similar and not force:
            lines = [f"  {pid}  {t}" for pid, t in similar]
            self._fail(
                "similar open proposal(s):\n" + "\n".join(lines) +
                "\nAdd detail with `owrap do proposal <id> note \"<text>\"`, "
                "or file anyway with --force."
            )
        store = self._store()
        store.mkdir(parents=True, exist_ok=True)
        with file_lock(store / ".lock"):
            pid = self._new_id(store, title)
            path = store / f"{pid}.md"
            write_atomic(path, self._document(pid, body))
        self._ok("add", id=pid, path=path)

    def get(self, what: str = None) -> None:
        """
        Print the template, one proposal, or the list of proposals.
        """
        if what == "template":
            self._ok("get", text=self._template())
            return
        if what and what != "all":
            self._ok("get", text=self._find(what).read_text().rstrip())
            return
        rows = []
        for path in sorted(self._store().glob("*.md")):
            meta = self._meta(path)
            if what != "all" and meta.get("status") not in OPEN_STATUSES:
                continue
            rows.append(
                f"{path.stem}  {meta.get('status', '?'):<8}  "
                f"{meta.get('author', '?')}  {self._title(path.read_text())}"
            )
        self._ok("get", text="\n".join(rows) or "(no open proposals)")

    def do(
        self, proposal_id: str = None, step: str = None, text: str = None,
    ) -> None:
        """
        Claim, close, or reject a proposal (owrap session only), or
        append a note (any session).
        """
        if proposal_id is None or step not in STEPS:
            self._usage("do")
        session = self._session()
        if step in OWNER_STEPS and not self._is_owner(session):
            self._fail(
                f"only the '{OWNER_PROJECT}' project session can {step} "
                "a proposal; add a note instead."
            )
        path = self._find(proposal_id)
        who = self._author(session)
        with file_lock(path.with_suffix(".lock")):
            content = path.read_text()
            if step == "note":
                if not text:
                    self._usage("do")
                content = self._add_note(content, who, text)
                message = "note added"
            else:
                status = {"claim": "claimed", "done": "done", "reject": "rejected"}[step]
                content = self._set_meta(content, "status", status)
                if text:
                    content = self._add_note(content, who, f"{status}: {text}")
                message = status
            write_atomic(path, content)
        self._ok("do", id=path.stem, text=message)


    # Private Methods

    def _store(self) -> Path:
        return docs_root(self._workspace()) / "proposals"

    def _template(self) -> str:
        return (TEMPLATES_DIR / "self" / "proposal.md").read_text().rstrip()

    def _read_body(self, file: str) -> str:
        if file == "-":
            return sys.stdin.read()
        path = Path(file).expanduser()
        if not path.is_file():
            self._fail(f"no such file: {file}")
        return path.read_text()

    def _session(self) -> dict:
        sid = os.environ.get("SESSION_ID", "").strip()
        if not sid:
            return {}
        return _parse(session_file(sid))

    def _is_owner(self, session: dict) -> bool:
        return (
            session.get("target_kind") == "project"
            and session.get("project_id") == OWNER_PROJECT
        )

    def _author(self, session: dict) -> str:
        project = session.get("project_id") or session.get("repository_id")
        if not project:
            return "unknown"
        sub = session.get("subproject_id")
        return f"{project}/{sub}" if sub else project

    def _find(self, proposal_id: str) -> Path:
        store = self._store()
        exact = store / f"{proposal_id}.md"
        if exact.is_file():
            return exact
        matches = sorted(store.glob(f"{proposal_id}*.md"))
        if len(matches) != 1:
            self._fail(
                f"no unique proposal matching '{proposal_id}'"
                if not matches else
                "ambiguous: " + ", ".join(p.stem for p in matches)
            )
        return matches[0]

    def _similar(self, title: str) -> list:
        """
        Open proposals whose title shares most of its significant words
        with `title`, as (id, title).
        """
        words = self._words(title)
        found = []
        for path in sorted(self._store().glob("*.md")):
            if self._meta(path).get("status") not in OPEN_STATUSES:
                continue
            other_title = self._title(path.read_text())
            other = self._words(other_title)
            shared = words & other
            smaller = min(len(words), len(other))
            if len(shared) >= 2 and smaller and len(shared) / smaller >= MATCH_OVERLAP:
                found.append((path.stem, other_title))
        return found

    def _document(self, pid: str, body: str) -> str:
        session = self._session()
        header = "\n".join([
            "---",
            f"id: {pid}",
            "status: open",
            f"author: {self._author(session)}",
            f"created: {time.strftime('%Y-%m-%d %H:%M')}",
            "---",
        ])
        return f"{header}\n\n{body.strip()}\n\n\n## Notes\n"

    def _add_note(self, content: str, who: str, text: str) -> str:
        line = f"- {time.strftime('%Y-%m-%d %H:%M')} {who} — {text}"
        return content.rstrip("\n") + f"\n{line}\n"

    def _new_id(self, store: Path, title: str) -> str:
        base = "-".join(re.findall(r"[a-z0-9]+", title.lower()))[:48].strip("-")
        base = base or "proposal"
        pid, n = base, 2
        while (store / f"{pid}.md").exists():
            pid = f"{base}-{n}"
            n += 1
        return pid


    # Static Methods

    @staticmethod
    def _title(content: str) -> str:
        """
        First `# ` heading after any front matter.
        """
        for line in Proposal._strip_meta(content).splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return "(untitled)"

    @staticmethod
    def _words(title: str) -> set:
        return {
            w for w in re.findall(r"[a-z0-9]+", title.lower())
            if len(w) > 2 and w not in STOPWORDS
        }

    @staticmethod
    def _strip_meta(content: str) -> str:
        if not content.startswith("---\n"):
            return content
        end = content.find("\n---", 4)
        return content[end + 4:] if end != -1 else content

    @staticmethod
    def _meta(path: Path) -> dict:
        content = path.read_text()
        if not content.startswith("---\n"):
            return {}
        end = content.find("\n---", 4)
        block = content[4:end] if end != -1 else ""
        return dict(
            (k.strip(), v.strip())
            for k, _, v in (line.partition(":") for line in block.splitlines())
            if k.strip()
        )

    @staticmethod
    def _set_meta(content: str, key: str, value: str) -> str:
        return re.sub(
            rf"^{key}:.*$", f"{key}: {value}", content, count=1, flags=re.M,
        )
