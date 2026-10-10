# Imported last -- each kind module imports its base class from this package.
from ..actions import Actions, added, supports
from ..actions.modify import Modify
from .run import Run
from .dispatch.agent import Agent
from .dispatch.exec import Exec
from .dispatch.fallback import Fallback
from .dispatch.read import Read
from .dispatch.task import Task
from .entry.decision import Decision
from .entry.todo import Todo
from .op.model import Model
from .op.permit import Permit
from .op.self import Self
from .op.setup import Setup
from .op.stat import Stat
from .op.sync import Sync
from .op.update import Update
from .record.backup import Backup
from .record.branch import Branch
from .record.repository import Repository
from .record.subproject import Subproject
from .run.ctx import Ctx
from .run.daemon import Daemon
from .run.project import Project
from .run.session import Session
from .run.updr import Updr
from .run.worktree import Worktree

KIND_REGISTRY = {
    "todo": Todo,
    "decision": Decision,
    "project": Project,
    "session": Session,
    "daemon": Daemon,
    "ctx": Ctx,
    "updr": Updr,
    "read": Read,
    "exec": Exec,
    "task": Task,
    "stat": Stat,
    "agent": Agent,
    "fallback": Fallback,
    "setup": Setup,
    "sync": Sync,
    "update": Update,
    "model": Model,
    "permit": Permit,
    "self": Self,
    "backup": Backup,
    "repository": Repository,
    "subproject": Subproject,
    "branch": Branch,
    "worktree": Worktree,
}

KIND_ALIASES = {"p": "permit"}

MODIFY_VERBS = added(Modify, Actions)
RUN_VERBS = added(Run, Modify)


def _build_action_registry() -> dict:
    """
    Map each `Modify`/`Run` verb to every kind that genuinely
    overrides it (`actions.supports`) -- derived from `KIND_REGISTRY`
    itself, so a kind rewrite never has to update a parallel list.
    `cli.py` uses this to resolve an action-first invocation with no
    kind token at all (`owrap start myproject`), the shim's grammar.
    """
    registry = {}
    for kind_name, cls in KIND_REGISTRY.items():
        for action in MODIFY_VERBS | RUN_VERBS:
            base = Run if action in RUN_VERBS else Modify
            if supports(cls, action, base):
                registry.setdefault(action, []).append(kind_name)
    return registry


ACTION_REGISTRY = _build_action_registry()
