# Kind/Action Architecture

Notes on the kind-first CLI rebuild (`owrap/actions/`, `owrap/kind/`,
`owrap/cli.py`), kept here so the design survives independently of any one
conversation. Supersedes the old `owrap/commands/*.py` + `owrap/runner.py`
dispatch, which stays frozen/untouched until this fully replaces it.

## Taxonomy

Two real action types, both in `owrap/actions/`:

- **`Access`** -- read-only. One verb: `get` (position-indexed lookup
  over a kind's `read`), plus a private `_path` property (where a
  record lives -- not a verb itself, see below).
- **`Modify`** -- everything that creates/changes/removes an
  identified thing's data, regardless of what shape that thing is (a
  markdown line-item, a project record, a live process). Verbs:
  `update`/`set`/`remove`/`add`/`clear`/`done`/`restore`. Each verb
  lives in its own one-file mixin under `actions/modify/`; `set` and
  `restore` are still skeletons (no kind uses them yet).

`Run(Modify)` adds the live-process verbs on top:
`start`/`stop`/`restart`/`attach`/`detach`/`refresh`/`kill`/`clean`
(`attach`/`detach`/`refresh`/`kill`/`clean` are skeletons until a kind
needs them beyond `Daemon`/`Session`'s current set). Every verb here is
also a one-file mixin, under `actions/run/`. `Run` itself is **not** an
action type -- see below.

`path` is **not a verb** -- it's `Access._path(target=None)`, a private
property of a kind (where its record lives), called internally (e.g. by
`_default_get`), never dispatched directly as `owrap <kind> path`.

**Kinds vs. action types -- the line.** `Access`/`Modify` are primitive,
composable verb categories with no idea what shape a kind is. `Entry`,
`Run`, and `Record` are statements about a *kind's shape* (bullet-entry-
in-markdown, live session/process, stored identity with no live
session) -- not action types. None has an `actions/<name>/__init__.py`
class for anything to inherit; each one's actual base lives under
`kind/<name>/__init__.py` instead, binding whichever action types that
shape needs:

```
owrap/kind/entry/__init__.py
    Entry(Modify, Access)

owrap/kind/run/__init__.py
    Run(Modify, Start, Stop, Restart, Attach, Detach, Refresh, Kill, Clean)

owrap/kind/record/__init__.py
    Record(Modify, Access)
```

**Why `Record`, not just more `Entry` kinds or a `Run` subclass.**
`Backup`/`Repository`/`Subproject`/`Branch` all have their own stored
identity (a directory/yaml, or for `Backup` a timestamped snapshot
directory) but no live session or process -- not `Entry`'s shape (none
of them is a bullet-entry line-item inside a *parent* record's
markdown section; they're the record, or a snapshot of one, in their
own right), and not `Run`'s either, even though `Project(Session)`
looks superficially similar: `Project` binds `Run`/`Session` because a
project genuinely *is* a session target (`start`/`attach`/`detach` a
window to it) -- `Repository` can be a session target too (a
repository-only session, started via `Session`'s own generic
machinery), but the `Repository` *kind* itself never had `start`/
`stop` even in the old system, so it doesn't earn `Run`'s shape, only
`Record`'s. Binds the same `Modify`/`Access` pair `Entry` does, but
isn't `Entry` -- different shape, different base, even though the
binding looks identical on paper. Mirrors `Entry`'s own role beyond
just binding, too: `_edit(func, *args, **kwargs)` plays the same part
`Entry._edit` plays for a bullet-entry kind (one place that turns an
expected error into a clean failure exit instead of a raw traceback),
and `_workspace(workspace=None)` resolves an explicit workspace
argument against the attached session's own instead of every kind
re-importing `identity.current_workspace` to do it inline. Every
concrete `Record` kind still overrides its verbs directly rather than
through `Modify`'s `_add`/`_update`/etc. callbacks (those assume a
project/repository memory-target to resolve and `_touch`, which
doesn't fit `Backup`'s repository-allowed target resolution or
`Repository`/`Subproject`'s rename/remove shape), but the error-
handling and workspace-resolution boilerplate that was repeated
~10 times across `repository.py`/`subproject.py`/`branch.py` before
this consolidation now goes through the base once.

**Why `Op`, not another `Record`/`Run`.** `setup`/`sync`/`update`/
`model`/`permit` (first bundled as one `Workspace(Run)` kind, then
split apart -- see Port status below) have no stored per-id record
(not `Record` -- there's no directory/yaml identified by an id, just
a workspace-level config file), no live session (not `Run`, despite
briefly living there), no async dispatch-and-poll (not `Dispatch`).
Each acts on one implicit target -- the current workspace's own
config/permit state -- rather than a resolved id. `kind/op/__init__.py`
binds `Op(Modify, Access)`, the same mixins `Record` binds, for the
same `set`/`get` verbs, but it's a distinct shape marker: no
`_workspace`/per-id resolution helper,
since there's no arbitrary record id to resolve against, just "the
current workspace," resolved inline per kind the same way `Project`
already does. Also carries `do`, declared once as a refusing stub on
`Actions` itself (not `Op`-specific -- see Port status below) so any
kind, any shape, can define the one verb that runs when it's invoked
with no action word at all.

`Project` isn't a separate shape -- it's a `Session` with its own extra
identity-level verbs (`update`/`add`/`set`/`get`) layered on top by plain
subclassing (`Project(Session)`), so it lives alongside `session.py`
under `kind/run/` rather than in a dedicated "spans more than one shape"
package. There's no kind that genuinely needs more than one `kind/`
base at once yet, so the `Composite` concept that used to anticipate
that case was dropped as unneeded dead weight -- it can come back if a
real multi-shape kind ever shows up.

**Why `Entry`, not `Document`.** The old name implied "lives in
markdown" was the defining trait; the defining trait is actually the
*shape* -- a bullet-entry line-item inside a parent record's section,
same thing every `Todo`/`Decision` already labeled itself with
(`shape = "section_entry"`, now removed as dead weight now that the
class name says the same thing with no separate string to keep in
sync). `kind/entry/__init__.py`'s `Entry(Modify, Access)` is the base
`Todo`/`Decision` inherit; since `Modify` already carries
`add`/`clear`/`done`/`restore` (previously homed in a now-dissolved
`actions/document/`), `Entry` doesn't need to import or bind them
separately at all -- inheriting `Modify` is enough.

**Why `add`/`clear`/`done`/`restore` moved into `Modify`, not a
separate category.** They used to live in `actions/document/` on the
theory that "document-shaped" kinds needed their own verb family.
That theory broke once `Session` (a `Run`-shaped kind, not an `Entry`)
needed `add`/`done`/`clear` too -- for an entirely different purpose:
`SessionWorkflow`'s `spawn`/`temp`/`branch` (create a child session) is
exactly `add`'s shape (mode as an argument, same way `Todo.add`'s shape
varies by position); `collapse`/`merge_branch` (fold a child's context,
and git code for branch mode, back into its parent) is exactly `done`'s
shape; `cleanup_branch`/the trash-retention sweep are both exactly
`clear`'s shape (bulk-remove, just targeting worktrees vs. old trash).
Two real, unrelated kinds needing the identical verb shape is the same
signal that promoted `write_atomic` to a utility (see Self-containment,
below) -- it meant `add`/`clear`/`done` were never document-specific,
just generically `Modify`-shaped verbs that happened to only have one
user so far. `restore` (the inverse of `remove`/`clear` -- un-trashing
something) joined the same family for the same reason, as a currently-
unused skeleton.

**Why `killservers`/`cleanup` became `Run` verbs (`kill`/`clean`), not
a new `Op`-shaped kind.** Both operate on `utils/dispatch/pool`'s
managed server fleet and session/context state -- the exact domain
`Daemon` already owns (`get_pool`/`shutdown_idle`/`ensure_min_servers`,
the `WORKERS` registry). `kill` is "`stop`, but every instance";
`clean` is a manual trigger of the same sweep `Daemon`'s loop already
does automatically. Neither has anything to do with "no identity, no
live state" -- they're squarely live-process verbs, so they belong on
`Run` directly (as `Daemon._on_kill`/`_on_clean`), renamed shorter per
preference (`kill`/`clean`, not `killservers`/`cleanup`). **PORTED.**

## Directory layout

```
owrap/actions/
    __init__.py     # Actions base (do/help/_fail/_edit/_resolve_target) +
                     # dispatch()/dispatch_kw()
    access/         # Access (real action type); get.py
    modify/         # Modify (real action type); update.py, set.py,
                     # remove.py, add.py, clear.py, done.py, restore.py
    run/            # NOT an action type -- start.py, stop.py, restart.py,
                     # attach.py, detach.py, refresh.py, kill.py, clean.py,
                     # eight plain mixins, and an empty __init__.py.

owrap/kind/
    __init__.py     # KIND_REGISTRY + KIND_ALIASES (today: p -> permit)
    entry/          # kind-level Entry (binds Modify/Access -- see
                     # above) + todo.py, decision.py
    run/            # kind-level Run (binds Modify + the run verbs
                     # together) + daemon.py, session.py, project.py
                     # (Project(Session) -- see Taxonomy), ctx.py, updr.py
    dispatch/       # kind-level Dispatch (binds Access + Start) +
                     # read.py, exec.py, task.py, agent.py, fallback.py --
                     # all PORTED, see Port status below.
    op/             # kind-level Op (binds Modify + Access, no per-id
                     # identity -- see Taxonomy) + setup.py, sync.py,
                     # update.py, model.py, permit.py, stat.py, self.py
                     # -- all PORTED, see Port status below. (A
                     # standalone wait.py was tried here too, then
                     # removed -- see the `wait` entry under Dispatch
                     # tooling.)
    record/         # kind-level Record (binds Modify + Access -- see
                     # below) + backup.py, repository.py, subproject.py,
                     # branch.py (Branch(Subproject)), and identity.py
                     # (shared current_workspace/resolve_identity/
                     # rename_backup_dir/update_sessions/
                     # attached_session_ids -- not a kind-level base
                     # itself, just the "one creation point" for logic
                     # no single Record-shaped kind owns; project.py
                     # under kind/run/ uses it too).

owrap/utils/staging.py          # New code's own copy of the root
                     # staging.py (template placeholder resolution,
                     # stage_all) -- old code keeps importing the
                     # untouched root original. See Self-containment
                     # below for why this is a copy, not a move.
owrap/utils/dispatch/constants.py  # New code's own subset of the root
                     # constants.py -- just the dispatch-lifecycle
                     # timeouts/messages every kind/dispatch/ kind
                     # needs, sitting alongside that folder's pool.py/
                     # terminal.py/watchdog.py. See Self-containment
                     # below.

owrap/dispatch/     # NOT owrap/server/ (one false start, corrected same
                     # session) and NOT owrap/runner/ (that name's taken
                     # by the old owrap/runner.py, still live) -- the
                     # domain folder for dispatching work into an
                     # attached session's server: manager.py (Manager --
                     # server lifecycle, task tracking, session context;
                     # shared by the session kind, every kind/dispatch/
                     # kind, and the daemon's pool.py), process.py,
                     # state.py, and work.py (the shared sentinel/
                     # SIGTERM/rc-normalization/log-prepend/context-
                     # injection lifecycle every kind/dispatch/ kind
                     # uses -- see Port status below).
    work.py         # Shared sentinel/SIGTERM/rc-normalization lifecycle
                     # for every Dispatch-shaped kind -- see Port status
                     # below.
    process.py      # server_responsive(url), find_port_pids(port) -- the
                     # single source for both; Manager._server_responsive/
                     # _find_port_pids just call these now.
    state.py        # read_state(path)/write_state(path, state) -- generic
                     # JSON state-file I/O; Manager._read_state/_write_state
                     # just call these now, passing self._state_file.
                     # Manager keeps thin delegating wrappers under the
                     # same method names for process.py/state.py both, so
                     # every existing caller (pool.py, session/stop.py,
                     # tests) is unaffected by any of this.

owrap/ctx/          # ctx/updr kinds' own dispatch pipeline -- see Port
                     # status below (state.py/excerpt.py/records.py/
                     # dispatch.py/manual.py/templates.py -- the
                     # CTX_*/excerpt-task template strings dispatch.py
                     # uses, split out of the old root constants.py,
                     # see Self-containment below). A second, independent
                     # implementation from the old commands/
                     # context_manager.py, which stays frozen for
                     # runner.py's sake.
    context.py      # context.md's own STRUCTURE (skeleton/header sync/
                     # section caps) -- the one place that defines what a
                     # context.md looks like, regardless of caller. Used
                     # to be two drifted copies: Manager.create_context
                     # (resync on every call, from config/ctx_state) and
                     # SessionWorkflow._create_context (one-shot blank
                     # skeleton for a freshly spawned session) -- the
                     # drift was real: Manager's skeleton silently lacked
                     # `## How To`, which `_cap_context_sections`/
                     # `records.merge_context` both already handled.
                     # Both callers now go through context.py's
                     # `ensure`/`sync_header`/`cap_sections`; `records.py`
                     # still owns the model-driven *content* merges
                     # (Focus/Decisions/etc from a dispatch), a separate
                     # concern from structure.

owrap/session/      # start.py/stop.py/attach.py/workflow.py/orientation.py
                     # (already here) plus resolver.py/trash.py/donow.py --
                     # COPIED (not moved) from owrap/utils/session/, same
                     # content, own internal imports adjusted for the new
                     # depth. New code (kind/run/session.py, kind/run/
                     # project.py, ctx/dispatch.py, ctx/manual.py, this
                     # folder's own attach.py/workflow.py) imports these
                     # copies; everything old (commands/*, runner.py,
                     # base.py, dispatch/manager.py) keeps importing the
                     # untouched originals at owrap/utils/session/ --
                     # same "two independent implementations, no forced
                     # rewiring of old callers" choice as `ctx` vs
                     # `commands/context_manager.py`. Not yet reconciled
                     # into one copy; a deliberate, named duplication for
                     # now, not an oversight. constants.py here too --
                     # TRASH_RETENTION_DAYS/NO_CONTEXT_MSG for trash.py/
                     # donow.py, split out of the old root constants.py,
                     # see Self-containment below.
```

## Grammar

`owrap <kind> <action> [args...]` — e.g. `owrap todo add myproject "text"`.
`KIND_REGISTRY` (`owrap/kind/__init__.py`) maps the first token to a class;
`dispatch()`/`dispatch_kw()` (`owrap/actions/__init__.py`) call the matching
method on it.

**Bare call, no args at all** (`owrap todo get`, nothing after the action):
`dispatch()` checks for a `_default_<action>` method on the kind before
calling the action itself. If present, that runs instead — a kind's own
answer to "what's the most useful thing to do with literally nothing to go
on." `get` is the verb that needs this today: `get` with an
explicit target but no position already does something sensible (lists
every item), but `get` with *nothing at all* defaults to reporting the
record's path instead of dumping every item — `Entry._default_get`
(kind-level, see above) calls `self._path()`; `Run`'s kind-level base has
its own version too (`Daemon` overrides it to report its pid). Every
other verb either requires real content (which already usage-exits
cleanly from inside its own callback) or takes no args at all
(`start`/`stop`/`restart`), so none of them need a `_default_<action>`.

**Bare call, no action word at all** (`owrap sync`, nothing after the
kind) is a different case, handled in `cli.py` itself rather than
`dispatch()`: if the kind overrides `do` (a refusing stub declared
once on `Actions`), that runs; otherwise `.help()` runs, same as
always. This is "what's the most useful thing to do with *no verb
specified at all*," one level up from `_default_<action>`'s "what's
most useful for *this* verb with nothing to go on" -- see Taxonomy's
`Op` entry and Port status below for which kinds define one.

## The generic verb pattern

**The kind-level `Entry` base does almost all the work.** `_touch`/
`_edit`/`_position` and generic `_add`/`_update`/`_remove`/`_clear`/`_done`
all live on `owrap/kind/entry/__init__.py`'s `Entry`. A concrete kind
(`Todo`, `Decision`) therefore defines *only* the raw item callback each
one delegates to -- `_add_item`, `_update_item`, `_remove_item`,
`_clear_items`, `_done_item` -- never the verb method itself, unless its
shape genuinely differs. Only `add` differs today: `Decision`'s add has no
position argument (unlike a goal's insert-before-position shape), so
`Decision` overrides `_add` directly instead of using the base's generic
one. The base's own `_add_item`/`_update_item`/`_remove_item`/
`_clear_items`/`_done_item` stubs raise "does not support `<verb>`" by
default, exactly like `Add`/`Clear`/`Done`'s own verb stubs do -- `Decision`
has no `_update_item`/`_done_item` at all, so calling either refuses
cleanly through the same stub.

Each verb is a mixin that does the *generic* flow and defers the
kind-specific part to a callback:

1. Resolve whatever the verb needs (a target, for `Modify`/`Access`'s
   verbs; nothing, for `Run`'s).
2. Call the kind's `_<verb>` callback for the actual payload/logic (for
   `get`, this is `read` via the internal `_get` accessor — see below).
   This callback raises "does not support `<verb>`" by default; a kind
   that doesn't override it never even reaches this: the public method
   checks support first and refuses immediately, so an unsupported verb
   fails cleanly without attempting to resolve anything or touch any
   state. How that check works depends on what's being checked:
   - For a regular method (`_add`, `_update`, ...): compare the bound
     function directly, `type(self)._update is Update._update`.
   - For a `@classmethod` (`read`): **this comparison doesn't work** --
     accessing a classmethod through a class returns a fresh bound-method
     object every time, so `is` is never `True` even when nothing
     overrides it. Use `hasattr(self, "read")` instead (`Get._get` does
     this).
3. Call the kind's optional `_on_<verb>` hook (a no-op by default) for any
   extra side effect beyond the core edit. If it returns an error message,
   fail with it instead of reporting success.
4. Report success via `_ok(verb, **fields)`, using the kind's own
   `messages`/`usage` dicts — never hardcoded per kind.

A kind whose verb genuinely doesn't fit this shape (e.g. `Project.update`,
which renames by an explicit id with no target to resolve at all, or
`Session.attach`/`start`/`refresh`/`restart`, whose output is a multi-part
orientation banner rather than one templated line) overrides the verb
method directly instead of defining the callback.

**`get` specifically** separates the raw fetch from the printed message:
`_get(target, position)` resolves the target, calls `read`, and returns the
*raw* item or list (position 0/-1 for first/last, `None`/`"all"` for every
item) — other code calls `_get` directly when it wants the value itself,
not a printed line. `get()` is the thin CLI-facing wrapper: calls `_get`,
then formats through `_format_item` (previewed/truncated by default via
`utils/parser/text.py`'s `preview()`) and reports via `_ok`.

**Getting rid of `utils/memory/records` in new code.** `_touch` (kind-level
`Entry`, bumps a project record's `last_updated` after an edit) used to
call `utils/memory/records.py`'s `touch_record_last_updated` -- the old
system's shared YAML-record helper. That module is otherwise exactly the
kind of frozen old-system code the porting rule says never to import, so
`_touch` now calls a fresh, self-contained `touch_last_updated` in
`utils/io/yaml.py` instead (same file-locked read/bump/write-atomic logic,
reimplemented, zero dependency on `records.py`). `utils/io/yaml.py` is
meant to hold every YAML-specific I/O helper the new system needs, the
same way `utils/io/atomic.py` holds the generic atomic-write one.

## Self-containment

If a kind is the only thing reading *and* mutating some piece of data, that
logic belongs **on the kind**, not in a shared `utils/` module — even if it
was factored out as a "utility" in the old system. `Todo`, for example, owns
its own goals-section parsing/editing entirely (`_edit_goals`, plus the
private `_section`/`_items` helpers) rather than importing
`utils/memory/goals.py`'s `edit_goals`.

The test for whether something stays in `utils/` instead: is it genuinely
called by more than one kind, or by code outside the kind system entirely?
`utils/dispatch/pool.py`'s daemon-control functions failed this test for
`Daemon` at first glance but turned out to have several other call sites
(`runner.py`, `session/start.py`, the pool's own self-heal) — so `Daemon`
got its own fresh, self-contained reimplementation instead of importing
them, exactly like `Todo` did, without touching those other call sites.

**The flip side of self-containment**: once a second kind genuinely needs
the exact same self-contained logic, it stops being "self-contained" and
becomes a real utility — pull it out into a `utils/` module instead of
copy-pasting it into the second kind. This happened with the atomic-write
helper (temp file in the same dir, copy permissions, `os.replace` over the
original): `Todo` and `Decision` each built their own goals/decisions
editing independently, but both ended up needing the identical few lines
to write the file back out. That's `utils/io/atomic.py`'s `write_atomic()`
now, used by both. The exact same pattern is why `add`/`clear`/`done`
ended up as `Modify` verbs rather than staying `Entry`-only (see
Taxonomy, above) -- `Session` turned out to need the identical shapes.
The rule either way: a self-contained kind stays self-contained until a
second real caller shows up — don't pre-extract a "utility"/shared verb
for a single caller, and don't duplicate once there's a second.

**`utils/` loose-file sweep (2026-10-10).** Two files that sat directly
under `utils/` genuinely belonged in an existing sibling domain, not at
the root: `filelock.py` moved to `utils/io/filelock.py` (`utils/io/
yaml.py` already imported it from there, the clearest signal); `process.py`
(just `is_alive(pid)`) merged into `owrap/dispatch/process.py` (same
package `server_responsive`/`find_port_pids` already lived in -- same
"process/port introspection" concern, one level up from `utils/`, not
under it), which also let two private `_pid_alive`-shaped duplicates in
`dispatch/work.py` collapse onto the shared one. `checkout.py`/
`harness.py`/`match.py` stay at `utils/` root -- each is small, single-
purpose, and used by too few/too unrelated callers to justify forcing
into an existing subdir (`parser/`, `io/`, `dispatch/`) that doesn't
actually fit; same tier as `paths.py`/`staging.py`, which are root by
design already.

**Keeping `owrap/`'s own root to just `cli.py`.** `constants.py` and
`staging.py` used to sit at the package root, genuinely shared by old
and new code both. Rather than edit their ~20 old importers (`runner.py`,
`base.py`, every `commands/*.py` that touches either), new code gets
its own copies, same "two independent implementations, no forced
rewiring of old callers" choice as `owrap/session/`'s copied files
(see Directory layout, above) -- old code keeps importing the
untouched root originals. `staging.py` is single-purpose (template
placeholder resolution, `stage_all`) and copies straight across to
`owrap/utils/staging.py`. `constants.py` is a grab-bag that doesn't
survive the copy as one file: only the names new code actually
imports moved, split by what they're *for*, not into a generic
`utils/constants.py` that would just be the same grab-bag one level
deeper. Dispatch-lifecycle timeouts/messages (`ANTI_SUMMARY_SUFFIX`,
every `*_KILL_S`/`NO_OUTPUT_*_S`/`INFRA_FAILURE_*_S`/`*_HARD_TIMEOUT_S`/
`AGENT_GRACE_*`, `MSG_MAX_CHARS`, `LOG_WRAP_WIDTH`,
`RECENT_TASK_RETENTION_S`) went to `owrap/utils/dispatch/constants.py`,
a sibling of that folder's existing `pool.py`/`terminal.py`/
`watchdog.py`. The `CTX_*` excerpt-task templates
(`CTX_SCOPED_TASK_TEMPLATE`/`CTX_CONTEXT_BLOCK`/`CTX_PROJECT_BLOCK`/
`CTX_REPOSITORY_BLOCK`/`CTX_IDLE_TIMEOUT_S`) went to `owrap/ctx/
templates.py` instead -- not under `utils/` at all, since `ctx/` is
already its own domain package and these templates have exactly one
caller, `ctx/dispatch.py`, which already lives right there. Same
reasoning gave `owrap/session/constants.py` (`TRASH_RETENTION_DAYS`,
`NO_CONTEXT_MSG`) to `session/trash.py`/`session/donow.py` -- those
are new code's own copies (see Directory layout's note on
`owrap/session/`), not the shared `workflow.py`/`start.py`/`stop.py`/
etc. group, so they needed their own non-root source too. Those
three still reach `..base.BaseRunner` at the package root, but
that's pre-existing coupling in the shared group, not something this
pass introduced -- left alone. Constants the old file has that
nothing in new code imports yet (`DECISION_*` thresholds,
`WATCHDOG_*_MSG`, etc.) were left behind in the untouched root
`constants.py` -- not copied speculatively for a caller that doesn't
exist yet.

**Accessors**: when other code needs *read* access to something a kind
owns, it goes through the kind's `get`/`_get` (see above), not `read`
directly — `read` is each kind's own internal data source for `get`, not
the public contract. Other current callers of the old utility (e.g.
`utils/memory/goals.py`'s `read_goals`, which `branch.py`/`get.py` still
use) keep using it unchanged until they're migrated — only new code goes
through the kind's `get`/`_get`.

## The daemon watchdog

The project's own Decisions/Goals log flagged that a non-gracefully-dead
daemon has nothing watching it -- `ensure_daemon` only ever got called
incidentally, by whatever happened to run next. That's now formalized:
`ensure_daemon()` moved its own enablement check
(`owrap_runner_enabled`/`owrap_context_manager_enabled`) up front, making
it safe to call unconditionally (a disabled config or an already-live
daemon are both cheap no-ops), and `owrap/cli.py`'s `main()` calls it on
every command except `daemon` itself (calling it there would race with
`daemon start`/`stop`/`restart`/`get`'s own liveness handling). Every
`owrap <kind> <action>` invocation through the new CLI now doubles as a
watchdog tick.

**Daemon's own liveness check, deduplicated.** `_stop_process`,
`ensure_daemon`, and `_default_get` all used to independently read
`DAEMON_PID_FILE` and probe `os.kill(pid, 0)`. That's the same self-
containment "flip side" as `write_atomic` -- three call sites inside the
same class is one too many to keep copy-pasting, so it's now one private
`Daemon._read_pid()` static helper (lock-free; every caller already holds
`DAEMON_LOCK_FILE` around it, and `flock` on the same path from the same
process would deadlock on a nested acquire).

**Why `Run` doesn't need `get()` wired up with real logic for every
kind.** `get` for a `Run` kind only ever happens as a bare call (`owrap
daemon get`, nothing after it) -- there's no stored list to index into,
so a position argument never makes sense. `dispatch()`'s zero-args
short-circuit to `_default_<action>` means a real `get()` method body is
never required beyond the kind-level `_default_get` stub: calling `owrap
daemon get <anything-with-args>` correctly refuses cleanly today
("daemon does not support get") simply because no kind overrides `get`
itself, args or not.

## Porting rule

New kind code never imports the old `*Runner`/`commands/*.py` classes it
supersedes — only low-level utility functions/constants (file locks, path
constants, parsing helpers), reimplemented fresh. Old files stay frozen
and untouched until the new system fully replaces them; never edit them
in place or redirect their call sites to the new kind classes.

**One narrow, explicit exception so far**: `owrap/session/start.py` and
`owrap/session/stop.py` *were* edited directly, because the goal there is
specifically to retire `BaseRunner`/`owrap/runner.py` -- each old
`*Runner.run()` body was extracted into a plain, self-contained function
(`start`/`stop`/`refresh`/`restart`), and the old class became a thin,
behavior-preserving wrapper calling it, so `runner.py`'s existing call
sites keep working unchanged. This is different from "redirecting an old
call site to a new kind class" (forbidden) -- the old classes still do
exactly what they did before, just via shared code now owned by the new
system instead of duplicated.

**Flagged, temporary exceptions**: none outstanding. `Project.update`/
`add`/`set`/`get` *were* this kind of exception (reaching into
`RenameRunner`/`ProjectRunner` in `commands.rename`/`commands.project`)
until ported fully self-contained directly into `kind/run/project.py`
-- no separate "rename" module needed; renaming a project is just what
`update` does. `Daemon._check_ctx` and `Session.attach`/`Session.detach`
were the same kind of exception (reaching into `commands.
context_manager`) until `ctx` got ported into `owrap/ctx/`. Every new
kind is now **PORTED**, not *ported* -- see Port status below.

**No `*Runner` classes remain anywhere under `owrap/`.** The thin
`XRunner(BaseRunner)` wrappers in `session/{start,stop}.py`
(`StartRunner`, `StopRunner`, `AttachRunner`, etc.) and the leftover
`session/stat.py::StatRunner` (437 lines, missed by the original
`owrap_old/` move) existed only to keep `owrap_old.runner`'s call
sites working -- once that stopped being a real constraint, they were
deleted outright rather than ported; new code already called the
plain functions/kind methods directly. `session/stat.py` moved to
`owrap_old/session_stat.py`. `Runner` only exists in `owrap_old/` now.

## Port status

By kind: every target verb it's meant to have, then what it actually has
today. **PORTED** (capitalized) = self-contained, nothing left to finish
-- no import of the old Runner class, and no reach into any other
not-yet-ported old module either. *ported* (lowercase) = the new code
exists and runs, but still reaches into an old module that hasn't been
ported itself yet (named each time, so it's traceable) -- finishing that
other port is what completes this one, not more work here.

**`todo`** (`Entry`) -- target: `add`/`update`/`remove`/`clear`/`done`/`get`.
Current: all six **PORTED**, fully self-contained.

**`decision`** (`Entry`) -- target: `add`/`remove`/`clear`/`get` (no
`update`/`done` -- not part of its shape).
Current: all four **PORTED**, fully self-contained.

**`daemon`** (`Run`) -- target: `start`/`stop`/`restart`/`get`/`kill`/`clean`.
Current: all six **PORTED**, including the real persistent loop's
pool-lifecycle half. The loop's `ctx` worker slot (`_check_ctx`) calls
`owrap.ctx.dispatch.check_all_attached` (see `ctx`/`updr` below and
Known Gaps), not `commands.context_manager`. `kill`/`clean` (renamed
from `killservers`/`cleanup`) are `Daemon._on_kill`/`_on_clean`, direct
behavior-preserving ports of the old `KillServersRunner`/
`CleanupRunner` bodies, split into one private method per sub-step.
Verified: `_kill_running_tasks` end to end against a real forked
process/sentinel, and `clean()` against this sandbox's live state
(removed five confirmed-dead server logs, left the live one alone).
The full pool/daemon-killing half of `_on_kill` was not run for real
(would have killed this sandbox's live daemon) -- straight,
unmodified port, not independently verified live.

**`session`** (`Run`) -- target: `start`/`stop`/`refresh`/`restart`/
`attach`/`detach` (`Run` proper) plus `add`(mode=spawn/temp)/
`done`(collapse+merge)/`clear`(cleanup_branch, trash-sweep)/
`restore` (all `Modify`, reused -- see Taxonomy) plus `end` (folds into
`stop`, not a separate verb).
Current: `start`/`refresh`/`restart`/`stop`(incl. the `force` reserved
keyword)/`add`(spawn/temp)/`done`(collapse/merge)/`clear`
(cleanup_branch)/`restore`/`attach`/`detach` all **PORTED**, fully
self-contained (no Runner class involved; `attach`/`detach` call
`owrap.ctx.state.register_ctx_state_window`/`prune_ctx_state_window`).
`stop force` (`owrap session stop force`) ports the old `StopRunner
(force=True)` path: `Daemon()._on_kill()` for the kill half,
`session.stop.force_stop()` (new, trash-sweeps every session plus the
global session pointer and every CCSID pointer) for the rest -- not
run for real here (would kill this sandbox's live daemon), same
reasoning as `Daemon._on_kill`'s own pool/daemon half. `end` needed no
separate port -- it already folds into `stop` (see target, above):
the plain `stop()` function's own current-or-target resolve-and-trash
flow already subsumes what the old `EndRunner` did.

**`project`** (`Run`, via `Project(Session)` -- `Modify` for its own
identity, everything `Session`/`Run` has via plain subclassing) --
target: `update` (rename), `add`
(create-or-select a subproject), `set` (select an existing subproject or
main, erroring if missing -- new semantic, not in the old CLI), `get`
(`name`/`path`/`subs`, `subs` default), plus everything `Session` has.
Current: `update`/`add`/`set`/`get` all **PORTED** -- rename and
subproject logic reimplemented as plain module-level functions
directly in `kind/run/project.py`, no `RenameRunner`/`ProjectRunner`
import; old `commands/rename.py`/`commands/project.py` stay frozen,
serving `runner.py` independently. `remove`/`clear` deliberately
deferred -- no clear target behavior defined for them yet.

**`repository`/`subproject`/`branch`** -- target: `add`/`update`/`remove`
(`attach`/`detach` for repository link/unlink; `done`=merge for branch).
**PORTED** -- see the full `repository`/`subproject`/`branch` entry
further below (kind/record/{repository,subproject,branch}.py); this line
used to say "not started" from an earlier pass, superseded once the
`Record` base landed -- no gap remains.

**`backup`** (newly identified `Modify`-shaped kind -- `BackupRunner`/
`RetrieveRunner`/`DeleteBackupRunner` were never a fourth category, just
`add`/`get`/`remove` on a `Backup` identity) -- target: `add` (create a
backup), `get` (retrieve/restore one), `remove` (delete one).
**PORTED** -- see the full `backup` entry further below.

**`ctx`/`updr`** (`Run`-shaped dispatch kinds) -- target: `start` (dispatch
a Context/Protocol pass), `done` (manual finalize), `add` (`touched`:
queue a touched-path entry for the next dispatch), likely `get`/status.
Current: `start`/`done` **PORTED** on both. The actual dispatch pipeline
(transcript read, prompt build, model call, job tracking, write-back --
formerly `CtxWorkerRunner`/`ManualCtxRunner`/`CtxHookRunner` in
`commands/context_manager.py`, 1744 lines) was ported into a new
top-level `owrap/ctx/` package, split by cohesion rather than kept as
one file (none of those three classes held real instance state --
textbook `style.md` "static-class namespace", so each became plain
module-level functions instead of a class):
- `owrap/ctx/state.py` -- ctx_state.json read/write (windows, touched
  entries, running tasks, dispatch-result bookkeeping)
- `owrap/ctx/excerpt.py` -- transcript timestamp/excerpt extraction
  (Claude + Codex)
- `owrap/ctx/records.py` -- record write-back/merge (project/repository
  facts, decisions, context.md merge)
- `owrap/ctx/dispatch.py` -- the dispatch core (`run`/`run_manual`/
  `check_all_attached`/model-call/retry/classification) plus `hook_run`
  (too small to stand alone, tightly coupled to what it spawns)
- `owrap/ctx/manual.py` -- the opencode-down manual fallback
  (`template`/`done`/`_check_manual_update_happened`)

`owrap.kind.run.ctx`/`updr.py`'s `start`/`done` call this package
directly -- fully self-contained, no Runner class, no reach into
`commands/`. `owrap.kind.run.ctx` also carries the module-level `main()`
that `run_manual`/`hook_run` spawn as their background worker
(`python -m owrap.kind.run.ctx --input <path>`), replacing the old
`python -m owrap.runner ctx-worker` target, but only for this new
package's own internal spawns. The *old* system (`commands/
context_manager.py`, `commands/kinds.py`'s old `Ctx`/`Updr` "Entity"
classes, `runner.py`'s `ctx-worker`/`ctx-hook`/`ctx-template` handlers)
is a second, complete, independent implementation, deliberately left
untouched -- the two never call into each other. `add`(`touched`) now
**PORTED** on `Updr` too, not just `Ctx` -- the exact "second real
caller needs the identical shape" trigger (see Self-containment,
above): both kinds feed the same per-window touched-entry queue that
`_dispatch` reads and clears regardless of which dispatch consumes
it, so the body moved out of `Ctx.add` into a shared `ctx/state.py::
queue_touched_paths(paths, note=None)` (raises `ValueError` for the
same two error cases `Ctx.add` used to `_fail` on directly, now
converted through `self._edit`), and `Updr.add` calls the same
function. `get`/status was never a real old-system feature on either
kind (`commands/kinds.py`'s old `Ctx`/`Updr` Entity classes only ever
had `start`/`done`), so there was no port target to match -- instead
`_default_get` (the zero-args fallback, same mechanism `Daemon`
uses) now reports the one thing `get` can usefully mean for a kind
with no stored items: path, last-dispatch status, and -- unless a
dispatch is still running -- a preview. `Ctx` reports its session's
`context.md` path (`context_path(sid)`); `Updr` reports the
session's resolved project/subproject-or-repository record path
(via `resolve_memory_target`, allowing a repository-only target
where `Actions._resolve_target` would refuse one -- same reasoning
`Backup`'s own target resolution already needed). Status comes from
a new shared `ctx/state.py::ctx_dispatch_status(session_id)`
(translates `set_ctx_dispatch_result`'s "pending" to "running", else
passes through "ok"/"failed"/"never run") -- shared because `Ctx`
and `Updr` both need the exact same read, and it's one combined
per-session status regardless of which kind's dispatch produced it,
not two independent ones. When finished, also reports when it last
ran and against what: `ctx/state.py::format_last_dispatch(session_id)`
reads `last_dispatch` (`{ts, kind, status, model, reason}`, the same
shape `set_ctx_dispatch_result` already writes) and formats "last
run: `<age>` ago (`<model>`)", appending the failure reason when
`status == "failed"` -- a third function alongside
`ctx_dispatch_status`/`ctx_last_dispatch` in the same shared-by-both-
kinds family. The preview itself uses `utils/parser/text.py::
preview_lines`, a new sibling to `preview` for whole-file/leading-
lines previews rather than `preview`'s short-item head/tail trim;
`age_str` (the age-formatting half) moved there too, promoted from a
private copy in `kind/op/stat.py` once `ctx/state.py` became a
second caller -- `Stat`'s own call sites now import the shared one.
Both **PORTED**. `check_all_attached`'s own rtlog/`context_jobs`
visibility gap (new system only) is fixed -- see Known Gaps below.

**`setup`/`sync`/`update`/`model`/`permit`** (`Op`) -- target: the old
flat `setup`/`sync`/`update-home`/`set model`/`permit` commands.
**PORTED** (`owrap/kind/op/{setup,sync,update,model,permit}.py`, from
`owrap/commands/{setup,sync,update_home,set_model}.py` and
`permit.py`'s `PermitRunner`/`PermitCmdRunner`). These were first
built as one bundled `Workspace(Run)` kind, then split apart: none of
them is a live-process/session verb (`Run`'s actual shape), and
grouping five unrelated single-purpose commands under one kind just
because they happen to share a config file was the wrong axis to
split on. Each now gets its own kind binding the new `Op(Modify,
Access)` base (no stored per-id record, no live session, no async
dispatch -- acts on one implicit target, the current workspace's own
config/permit state, rather than a resolved id) plus its own `do`,
the single verb that runs when the kind is invoked with no action
word at all (`owrap sync` == `owrap sync do`; `owrap setup`/`owrap
update` still need `do <args>` spelled out since their argument is
mandatory and would otherwise be mistaken for an action name). `do`
itself is declared once, as a refusing stub on `Actions` (so any
kind, any shape, can define one) -- `cli.py`'s bare-kind branch calls
it instead of `.help()` when a kind overrides it. It is **not** an
alias for `start`; a kind's `do` and `start` can mean genuinely
different things on the same kind (not yet needed on any port, but
`Dispatch` kinds are free to define their own `do` independent of
`start`).

`Permit.do` **is** `owrap p`, the raw stdin-JSON permission-check
hook opencode invokes directly with no action word -- the exact
bare-kind-dispatch case `do` exists for, not a special case bolted on
top of it. `p` is a `KIND_ALIASES` short name for `permit` (`kind/
__init__.py`), so `owrap p` (opencode's own invocation) and `owrap
permit` (everything else) resolve to the same kind with no collision:
the hook always calls it bare (stdin payload, zero argv tokens after
the kind name), while `set`/`get` always carry an explicit action
word. `Permit.set` generalizes the old `bypass-all on/off` single
toggle into `set <name> <on|off>` against a small `FLAGS` name table
(today still just `bypass-all`), while keeping `set <on|off>` as
shorthand for `set bypass-all <on|off>` -- `DEFAULT_FLAG` -- since
that is still the one flag anyone actually toggles day to day; `get`
is unchanged (permit status report). `update`'s `--migrate` path
reuses `Daemon()._on_kill()` and `kind/run/daemon.py`'s `_kill_pid`/
`_wait_dead` rather than a third copy; its re-sync subprocess call
now targets `python -m owrap.cli sync` (the new CLI, unlike the old
`commands/update_home.py`'s untouched original). **Known, not fixed**:
the old `_resync_current_workspace` watches stdout for a
`"sync_task written: "` line nothing prints, so its "auto re-synced"
success message can never actually fire even when the re-sync works
-- a pre-existing cosmetic bug, preserved as-is. Verified `get`/
`do(dry_run=True)`/`set` byte-for-byte against the old runners for
real, plus the raw `owrap p` hook round trip; `--migrate` without
`dry_run` (stops the live daemon, moves `OWRAP_HOME`) deliberately
not run for real.

**`touched`** -- `Ctx.add(*paths, note=None)`. **PORTED.** Already had
everything it needed: `ctx.state.append_touched_entries` and
`owrap_sid_for_ccsid` were both ported in an earlier pass, so this
was a direct call-through, verified against the old `TouchedRunner`'s
no-attached-session error path (same message content, new system's
own `ERROR: ...` + `exit(2)` convention in place of the old bare
`print`/`exit(1)`, consistent with every other kind this session).

**`backup`/`retrieve`/`delete`** -- no new verb names: `backup`→
`add`, `retrieve`'s listing half→`get`, `retrieve`'s restore half→
`restore` (the previously-unused `Restore` skeleton), `delete`→
`remove`. **PORTED** (`owrap/kind/record/backup.py`, from `owrap/
commands/backup.py`'s `BackupRunner`/`RetrieveRunner`/
`DeleteBackupRunner`). `Backup(Record)` -- a timestamped snapshot
directory isn't a markdown bullet-entry (not `Entry`); its own target
resolution (`_resolve_backup_target`) allows a repository-only target,
where `Actions._resolve_target` deliberately refuses one. Every verb
overridden directly (same reason `Project`/the `Op` kinds do), target-
resolution errors go through `Record._edit`. Verified the pure helper
logic and the shared error path live; a full `add`→`get`→`restore`→
`remove` round trip wasn't possible in this sandbox (no `docs_root`
configured here).

**`repository`/`subproject`/`branch`** -- a second old `KIND_REGISTRY`
(`owrap/commands/kinds.py`), covering project-adjacent identity
records with zero new-system coverage until now. **PORTED**
(`owrap/kind/record/repository.py`, `subproject.py`, `branch.py`),
each fully self-contained -- no old `commands/` import, same
principle `Project` established. These, plus `Backup`, share a new
kind-level base, `Record(Modify, Access)` under `kind/record/
__init__.py` -- parallel to `Entry`/`Run`: `_edit`/`_workspace` play
the same role `Entry._edit`/`_touch` play for `Todo`/`Decision`.
`owrap/kind/record/identity.py` holds the shared `current_workspace`/
`resolve_identity`/`rename_backup_dir`/`update_sessions`/
`attached_session_ids` logic (also used by `kind/run/project.py`).
- `Repository(Record, Attach, Detach)` -- `add`/`update`(rename, incl.
  cross-project reference fixup)/`remove`, plus `attach`/`detach`
  reused for repo-link/unlink (same verb names `Session` uses for a
  window binding, repurposed for a different relation).
- `Subproject(Record)` -- `update`/`remove` only; creating one is
  `Project.add`/`Project.set`'s job.
- `Branch(Subproject)` -- inherits `update`/`remove`; `add`/`done`
  (merge) are its own.

Verified every new verb's error path against the old system's
wrapped exception handling (not the bare `Entity` class) -- identical
output for `repository add/update/remove/attach/detach`, `subproject
update/remove`, `branch add/done`, `backup add`.

**Dispatch tooling** (`read`/`run`/`agent`/`exec`/`work`/`abort`/
`agents`/`wait`/`f`, today's `orun`/`oexec`/`oagent`) -- a different
surface entirely (dispatches *into* sessions, rather than managing them),
currently disabled per planner mode regardless, but no longer blocked
on scoping: this set shares one real lifecycle (dispatch a unit of
work on the attached session's server, block until it finishes, track
it via a sentinel) -- not a new action type (`start`/`get` already
exist on `Start`/`Access`; no new primitive verb needed), just a new
kind-level base, `Dispatch(Access, Start)`, under `kind/dispatch/`.
Not just an empty binding, either: `Dispatch.get(task_id)` is real
shared logic every concrete kind gets for free -- a status lookup
scoped to that kind's own tasks (`work.find_task(task_id, kind=self.
kind)`), which `Task` then reuses unscoped for its cross-kind version.
Mapping from old commands to new kinds:
- `read` -- `Read` kind, `start`. **PORTED**.
- `exec` -- `Exec` kind, `start`. **PORTED** -- the long-running
  "work through the plan" dispatch; on success also refreshes the
  session's context-plan/frequent-files state via `Manager`.
- `run` -- absorbed into `Task` (name dropped to avoid colliding with
  the `Run` kind-base). `Task.start` = old msg/task dispatch.
  **PORTED** -- split into `_start_msg`/`_start_task_{attached,
  fallback}`, calling the same `work.*`/`Manager` primitives `Read`/
  `Exec` use. Verified against original error text for oversized/
  newline msgs and empty `input_path`.
- `agent` -- `Agent` kind, `start`. **PORTED** -- timeout+grace period,
  inline-vs-`--taskf` split, extracts `## Summary` into the session's
  digest. `agents clear` absorbed as `Agent.clear()`. Verified against
  old `AgentsRunner` byte-for-byte.
- `abort`/`wait` -- `abort` is `Task.done(target)`. **PORTED** --
  forces a running sentinel to `aborted` via SIGTERM, verified end to
  end against a real subprocess. `Task.get(task_id)` **PORTED** (cross-
  kind `Dispatch.get`). The old `wait` (log-file marker polling, no
  sentinel/`RUNNING_DIR` involved) doesn't fit this lifecycle --
  deliberately left out of `Task`/`Dispatch`. **Not started** here.
- `f` -- `Fallback` kind, `start`/`done`/`get`. **PORTED** -- its own
  status-file state machine (mode-addressed, not task-id), independent
  of the sentinel/pool machinery by design (must work when the normal
  path is down). Verified `done`/`get` end to end against a real
  forked process and fabricated status file.
- `stat` -- `Stat` kind. **PORTED**, moved from `kind/dispatch/` to
  `kind/op/` (its "id" is a session filter, not a task id). `do()` =
  full report; `get(<session_id>)` = filtered, now required. Reuses
  `work.format_task_status` for task rendering rather than its own.
  Verified byte-for-byte against the old `StatRunner.run()` output for
  a live session id.
- `wait` (old `WaitRunner`: polls a log file or the input queue for a
  marker) -- tried as a standalone kind, then removed: nothing calls
  it, and it doesn't overlap with the `wait` *action* (see Taxonomy/
  `Run` actions) that `Session`/`Ctx`/`Updr` already use for their
  own job-polling needs (that one polls `context_jobs`; this would
  poll raw log files -- a real caller never showed up). **Not
  started** -- see `Task`/`Dispatch`'s own `wait` entry in Known Gaps,
  same conclusion.

Shared service layer: `owrap/dispatch/work.py` (not `task.py` -- avoids
confusion with the `Task` kind) ports `base.py`'s `BaseRunner`
lifecycle (sentinel write/complete, SIGTERM handling, `allow_all()`)
as plain module-level functions, a `state` dict replacing the old
per-instance kill flags. `prepend_log_entry` collapses three near-
identical flock-protected log-prepend methods (`Read`/`Task`/`Exec`)
into one. `should_inject_context`/`context_prefix`/`context_block`
collapse the five-times-repeated context-injection gate and its two
distinct renderings (inline prefix vs. `## Context` block) across
`Read`/`Exec`/`Task`'s three start paths. Lives at `owrap/dispatch/`
alongside `Manager`, not `owrap/server/`/`owrap/runner/` (the latter
collides with the still-live `owrap/runner.py`).

**Old syntax sugar, not a port target**: `update`/`rename`/`add`/
`remove`/`clear`/`done`/`get`/`set` (bare, action-first over the old
`commands/kinds.py`) just reach the same kinds listed above through a
different old-CLI spelling -- nothing new to port here.

## Known Gaps

Running list of concrete, identified gaps in the new system -- not
design debt, specific unfinished or broken behavior. Each either has
a TODO logged on the `owrap` project or is deliberately deferred with
a stated reason; update this list rather than letting gaps live only
in Port status prose.

- ~~Daemon's background ctx auto-dispatch invisible to rtlog/`owrap
  stat`~~ **FIXED** (2026-10-10, TODO closed): `check_all_attached()`
  (new system only -- the old `commands/context_manager.py` copy has
  the identical gap and stays frozen/unfixed, reference-only) now
  wraps each window's dispatch in a new `_dispatch_and_track()`
  helper: creates a job via `context_jobs.create(..., "auto")`,
  marks it running (matching `run()`'s own create/running/finish
  bookkeeping for a manual dispatch), calls `_dispatch_tracked` with
  that `job_dir`, and finishes the job in a `finally` so a raised
  exception still closes it out as failed rather than leaving it
  stuck "running" forever (verified: a forced exception from
  `_dispatch_tracked` produces a `context_jobs` entry with
  `status="failed"`, `rc=1`, and `check_all_attached` itself still
  doesn't raise). Verified end to end: `context_jobs.recent(sid)`
  shows the job, and rtlog gets the real `ctx.queued`/`ctx.progress`/
  `ctx.done` sequence for an automatic dispatch for the first time.
  One side effect worth knowing, not fixed further: every daemon
  tick now creates a job per attached window even when there's
  nothing new to summarize (same as a manual `--ctx` with an empty
  diff already does -- `_dispatch` returns rc=0 either way, "nothing
  to summarize" isn't a distinct status) -- `owrap stat`'s own
  `RECENT_TASK_RETENTION_S` (120s) keeps these out of the display
  quickly, but the job directories themselves accumulate on disk
  like manual ones already do; no retention sweep exists for either,
  pre-existing, not introduced here. Covered by
  `tests/test_revised_ctx_auto_dispatch.py` (4 tests: job created on
  success, job finished-as-failed on a raised exception, codex
  window tracked too, config-disabled short-circuits before any
  lookup).
- **`owrap get <what>` had no new-code equivalent at all -- mostly
  closed now.** Found during a full audit of `owrap_old/utils/
  cli_schema.py`'s subcommand list against `KIND_REGISTRY`; the old
  `GetRunner` (`owrap_old/commands/get.py`) was a multi-purpose
  introspection command with over a dozen `what` targets. Resolution:
  no new kind-shape needed for most of them -- each maps onto a kind
  that already existed but didn't override `get`/`_default_get`
  (or did so too narrowly), the exact split `_default_<action>`
  exists for (bare call means one thing, `get` with args means
  another -- `Daemon` already used this for its own pid report).
  - `home`/`self`/`opencode` (explicitly no session needed) -- new
    `Self(Op)` kind (`owrap/kind/op/self.py`): `do()` = staged
    `self.md` content (also `get()` bare); `get("home")` = `OWRAP_HOME`;
    `get("opencode"[, "reason"])` = the shared health flag, via the
    already-existing `ctx/dispatch.py::read_opencode_status_detail`.
  - `session`/`project-id`/`subproject`/`repository` -- `Session`
    had no `get` at all; `Session._default_get()` now prints the
    identity-field table, making the three single-field lookups
    redundant (the table already has them).
  - `agents` -- `Agent.get(task_id)`'s contract (one dispatch's own
    status) couldn't change; `Agent._default_get()` (bare) now covers
    the session's accumulated digest instead, the same split.
  - `decisions` -- was a computed count + prune-threshold notice, not
    a listing; `Decision._default_get()` now reports that, while
    `Decision.get(target, position)` (with args) keeps listing items.
  - `memory` -- `Updr.get("memory")` now loops every linked repository
    (`target.repository_paths`), printing each with a preview; the
    bare `_default_get()` keeps reporting the single project/
    repository record it already did.
  - ~~`config`/`plan`/`input`~~ **DONE** (2026-10-10): decided owner
    is `Self`, same as `opencode` already was -- `config` (the
    attached session's workspace config, full JSON dump) and `plan`/
    `input` are really `Session`/`Project`-scoped data, but `Self` is
    the one *serving* them (`get("config"|"plan"|"input")`), the
    same split as `opencode`'s health flag being a fact owned by
    `ctx/dispatch.py`, not any kind. `owrap get <what>` is now fully
    closed -- no open targets remain. Covered by 27 new tests
    (`test_revised_get_facets.py` + `test_revised_decision.py`'s
    threshold cases).
- **`Task`/`Dispatch`**: the old log-marker-polling `wait` concept has
  no home -- doesn't fit the sentinel/`RUNNING_DIR` model `Dispatch`
  shares, and is unrelated to the `wait` action used by `Session`/
  `Ctx`/`Updr`. Unassigned, not planned unless a real caller shows up.
- **`owrap_old/` is reference-only.** Relocated old-only code
  (`commands/`, `runner.py`, root `staging.py`, `utils/{actions,
  arg_parser,cli_schema}.py`) was moved there for historical reference,
  not required to import cleanly, run, or pass its own tests (`tests_
  old/`, never collected by pytest). Do not rely on it as a working
  package or "fix" it as if it were live code.
- ~~**Shim cutover**~~ **DONE** (2026-10-10) -- see next section.
  `end` is the one verb still deliberately left unported; `branch`
  is now a real kind (`worktree`), tracked separately below.
- ~~**`branch`**~~ **DONE** (2026-10-10): new `owrap/kind/run/
  worktree.py` -- `Worktree(Run)`, `add`/`done`/`clear` wrapping
  `SessionWorkflow.create(mode="branch", ...)`/`merge_branch`/
  `cleanup_branch` directly. Pulled wholesale out of `Session`, which
  had been carrying all three already: `Session.clear()`'s entire
  body was `cleanup_branch` and nothing else; `Session.done()`
  branched on the literal string `"merge"` to switch from ordinary
  collapse to a real Git merge; `Session.add()` never even exposed
  the missing `mode="branch"` create case (only `temp`). `Session`
  now has none of this -- `done`/`clear` are purely session-collapse
  verbs, `add` is purely spawn/temp. Avoids the `branch`/`Branch`
  (`Subproject`-shaped doc-branch) name collision outright, the real
  reason a dedicated kind was the right call instead of just adding
  the missing `add` case alongside `Session`'s existing keywords.
  8 new tests in `tests/test_revised_worktree.py`, including that
  `Session` genuinely dropped `clear` (`does not support clear`) and
  no longer special-cases `"merge"`.
- **`end`** -- confirmed NOT redundant with `done`/`stop` on
  inspection (recovered its deleted source, `owrap/session/end.py`,
  from git history: it hard-deletes one session's context/lock/
  session files outright, no parent-child relationship required and
  no trash step at all) -- genuinely distinct from both `stop`
  (trash, reversible) and `done` (parent-child collapse). Decided:
  not porting it -- `stop` already covers "I'm done with this
  session," with the added safety of trash + `restore`; `end`'s
  skip-the-trash behavior reads as a workaround for a system that
  had no trash step yet, not a need that survives having one. Same
  treatment as `Task`/`Dispatch`'s own `wait`: deliberately
  unassigned, not planned unless a real caller shows up.

## The shim is switched over

`bin/owrap` (the template `update.py::install_shims` renders into
`files/bin/` for a dev checkout, or `~/bin/` live) now dispatches
through `python3 -m owrap.cli` by default instead of
`owrap.runner`. `p`/`permit`, and `set` reaching `Permit`/`Model`
directly through `KIND_REGISTRY`, were never a gap on the new side
to begin with (see Port status above).

**`cli.py`'s global-flag gap is fixed.** `_strip_global_flags(argv)`
removes `-a`/`--allow-all` and `--shell-pid <pid>` wherever they
appear in argv, before kind/action parsing -- both were only ever
needed by the old runner (`allow_all` is config-driven via
`work.allow_all()` on the new side; `shell_pid` fed a session-
identity fallback the new resolver doesn't use), so the rewritten
shim no longer sends either at all; stripping them stays as
tolerance for a caller that still does. Verified with 3 tests in
`tests/test_revised_cli_dispatch.py`.

**The grammar mismatch is resolved via a dynamically-derived action
registry, not a hand-maintained translation table.** `cli.py` was
purely kind-first (`owrap <kind> <action>` -- `argv[0]` had to be a
`KIND_REGISTRY`/`KIND_ALIASES` name); the shim's own grammar is
action-first (`owrap start myproject`, `owrap add todo proj text`
-- `argv[0]` is a verb, sometimes followed by an explicit kind
token, sometimes not). `owrap.kind.ACTION_REGISTRY` maps every verb
to every kind that genuinely overrides it, derived once at import
time from the class hierarchy itself (`actions.added`/
`actions.supports` -- checks whether a kind overrides a verb's
public method directly or its private `_<verb>`/`_on_<verb>` hook,
the same check each mixin's own refusing stub already makes) --
never a per-kind list, so a kind rewrite needs no parallel upkeep.
`cli.py`'s new `_resolve_kind_first()` uses it to reorder an
action-first call onto the kind-first shape: swap when the next
token already names a supporting kind, otherwise fall back to the
single supporting kind, preferring `session` on a genuine tie (the
`Session`/`Daemon` lifecycle-verb collision on `start`/`stop`/
`restart` -- both override it, one directly, one via `_on_<verb>`,
but old grammar's bare, kind-less form always meant the session;
`daemon start`/`stop`/`restart` stay reachable kind-first as
before). Verified with 6 tests in
`tests/test_revised_cli_action_first.py` and 9 in
`tests/test_revised_action_registry.py`.

**Per-kind `--flag`s now work too, closing a related, previously
separate gap.** `dispatch()` splits `--flag`/`--flag value` tokens
out of `args` by matching the resolved method's own
`inspect.signature` (a bare switch if the parameter's default is
`False`, a value flag otherwise), before the existing positional-
padding step -- which itself was fixed alongside this to pad a
still-missing parameter with its own real default instead of a
blind `None` (harmless when a default is `None` already, but wrong
for a `bool` default, which this flag-splitting newly exercises).
Verified with 5 tests in `tests/test_revised_dispatch_flags.py`.

**That flag-splitting is only as good as each kind's own parameter
names, and four had drifted from what their own `usage` dict already
promised** -- found while scoping the `oread`/`oagent`/`oexec`/
`orun` -> plain `owrap read`/`agent`/`exec`/`task` consolidation.
`usage` text is hand-written prose for `-h`/error output;
`inspect.signature` is the only thing `_split_flags` actually reads
-- the two can drift, and did: `Read.start`'s `read_id`, `Agent.
start`'s `agent_id`, and `Task.start`'s `msg_id`/`input_path` each
already documented `--id`/`--input` but took a differently-named
parameter, so neither flag ever actually reached the method;
`Exec.start`'s `disablewd` likewise documented `--no-watchdog`.
Fixed by renaming the parameters to match what was already
documented (the `usage` dict is the user-facing contract; the
parameter name should follow it, not the other way round) -- each
rename scoped to the public `start()` signature only, leaving each
private helper's own same-named parameter (a different scope)
untouched. Short flags (`-i`, `-s`, `-d`, `-g`) the old shims
normalized in bash have no equivalent at all now -- `_split_flags`
only ever matches `--long-form` tokens; not decided whether that's
a deliberate simplification or a gap, since nothing depends on it
yet. The shim consolidation itself (one `owrap` binary instead of
five) is not done -- this was scoping work for it, not the cutover.

**Session-id autodiscovery, fixed in `bin/owrap` (the live
template source -- the production-installed shim before this
session's work, and this repo's standalone `bin/` directory before
this cutover, are both preserved untouched at `bin_old/`).**
`_resolve_owrap_session()` is the one piece of session-identity
resolution that lives in bash, not Python (`cli.py` and `runner.py`
both just read `$SESSION_ID`). Two real bugs found and fixed here,
independent of the cutover itself: it never checked
`CODEX_SESSION_ID` at all (Python already writes a pointer for it
-- `codex_session_id_pointer()`, same `_pointer()` helper as
CCSID/opencode-run-id -- the shim just never read it), and it
pointed at the old flat pointer-dir layout (`sessions/by_ccsid`/
`sessions/by_opencode_run_id`) and flat `<sid>.session` file, both
superseded by the current `sessions/_index/{claude,opencode,codex}`
pointer dirs and per-session `sessions/<sid>/.session` directory
(`session_file()` in both resolver copies falls back to the flat
name only for not-yet-migrated sessions) -- the shim now checks the
per-session path first, flat path second, matching that fallback
order exactly.

**`bin/` reorganized**: the repo's top-level `bin/` (the real
template source `update.py::install_shims` reads from -- separate
from `files/bin/`, which is only its rendered dev-mode output) was
stale relative to what was actually running, since the dev-mode
output had been hand-patched out of band rather than through the
template. The stale set is preserved at `bin_old/`; `bin/owrap` is
the rewrite, and `orun`/`oexec`/`oread`/`owait`/`oagent`/
`auto_comp.sh` moved over unchanged.

**`bin/owrap` ended up with zero verb-specific logic at all, not a
translation layer.** `spawn`/`temp`/`collapse`/`branch`/`end` were
never anything but old shim-grammar names for `Session.add`/
`Session.add("temp", ...)`/`Session.done()`/`Worktree`'s three verbs
-- the only thing that actually *needed* them was the planner's own
staged docs (`templates/self/sessions.md`, `templates/self/
commands.md`), which still taught the old syntax. Updating those two
templates to the real syntax (`owrap session add`/`owrap session add
temp`/`owrap session done`/`owrap worktree add|done|clear`/`owrap
stop`) removed the only reason a translation layer would exist, so
there isn't one -- `bin/owrap` is purely the session-id ingester
(`_resolve_owrap_session`, irreducibly bash: it exports into the
*calling* shell's environment, which a child Python process can't
do) plus a thin wrapper around `python3 -m owrap.cli "$@"` that
re-exports `SESSION_ID` if the call minted or changed one. Found
along the way: `owrap.runner` -- the module these verbs, and all
five helper shims, called -- doesn't exist anymore at all (it fully
relocated to `owrap_old/` and was never left as a working shim
target); `owrap branch`/`owrap end` were two confirmed live outages
before this fix, not latent risk. `end` fails cleanly now by simply
not matching any kind or `ACTION_REGISTRY` verb (the generic "no
such kind" error) rather than crashing. `python3 update.py`
re-renders `files/bin/` from the new template; verified end to end
against a live shell (`todo get`, `self get home`, `end`, an unknown
token).

**A `Dispatch` kind can now be called with no action word at all,
restoring the old per-binary shims' real UX** (`cli.py`, not the
shim): `oread file.py`/`oagent "task"`/`oexec --no-watchdog` never
had an action word -- the whole binary *was* the action. `main()`
now treats an unrecognized action token on a `Dispatch`-shaped kind
(`Read`/`Agent`/`Exec`/`Task`) as `start`'s own first argument
instead of erroring, checked via `issubclass(cls, Dispatch)` plus
`getattr(instance, action, None) is None` so a real action
(`get`/`done`/`clear`, or an explicit `start`) is never
reinterpreted. Verified with 4 tests in
`tests/test_revised_cli_dispatch.py`.

~~**`oread`/`oagent`/`oexec`/`orun`/`owait`**~~ **DONE** (2026-10-10):
deleted outright, from `bin/`, `files/bin/`, and `update.py`'s
`SHIMS` tuple (now just `("owrap",)`) -- nothing used them but the
planner's own staged docs, which taught the old syntax; updating
`templates/self/{sessions,commands}.md` to the real one (plus
`templates/{planner,executor}.md`, `templates/{claude,codex}/
allow.json`, and `README.md`) removed the only reason they existed.
`main()` in `cli.py` gained the matching half: an unrecognized action
on a `Dispatch` kind (`Read`/`Agent`/`Exec`/`Task`) is now `start`'s
own first argument instead of an error (`owrap read file.py`, not
`owrap read start file.py`) -- the old per-binary shims' real UX,
restored without any shim-side logic.

**Short flags are back too, closing that gap as a real one, not an
open question.** Audited every short flag the old `read`/`run`/
`agent`/`exec` argparse schemas actually declared (`-f` is skippable
-- the new side's positional `file_path` already covers it): `-g`
grep, `-s` summarise, `-d` details, `-v` verbose, `-p` prompt-style,
`-i` id, `-m` model, `-t` timeout. `actions.SHORT_FLAGS` aliases each
to its long parameter name inside `_split_flags`; each only fires
for a method that actually declares that parameter, so it stays
scoped per kind automatically, same principle as `ACTION_REGISTRY`.
Verified with 2 tests in `tests/test_revised_dispatch_flags.py`.

**Found and fixed a real, previously-masked bug in `dispatch()`
while verifying `--project`/`--subproject`/`--repository`** (`owrap
start`'s own documented flags, in CLAUDE.md's Planner Working Manual
-- never actually forwarded by `Session.start()` until now, which
only ever exposed a bare `project_name` positional despite
`session.start()` already supporting all three). Once any parameter
is supplied by flag, the positional-padding step was splicing
leftover positionals back in *by position*, not by name -- fine
when the flagged parameter was always the trailing one (every case
so far), wrong the moment one sits in the middle of a signature
(`project` sits between `project_name` and `repository`): the next
positional silently landed on the wrong parameter instead of raising.
Fixed by binding every remaining slot by name once any flag is used,
with the positional overflow case (too many args) still passed
through positionally so it still raises its own clear error instead
of being silently dropped. Verified with 2 tests in
`tests/test_revised_dispatch_flags.py` (the middle-parameter
regression case).

**`--project`/`--subproject`/`--repository` themselves were then
retired, not kept.** Project targeting already has a clean kind-first
path (`Project` inherits `Session.start` unchanged, so `owrap project
start <id>` and bare `owrap start <id>` both just work off the
existing positional `project_name`); subproject selection is `owrap
project add`/`owrap project set` post-start. `owrap main`/`owrap
sub`/`owrap subs` were dead names already (`_resolve_kind_first`
returned `None` for all three) — docs described a grammar that had
quietly stopped existing, same pattern as the earlier `spawn`/`temp`/
`collapse` cleanup. `--repository` (repository-only sessions,
`target_kind=repository`) had no equally clean kind-first
replacement — `Repository`'s own `attach`/`detach` (repo↔project
linking) collide in name with `Session`'s (window↔session binding),
so it couldn't just inherit `Session` the way `Project` does — and
was dropped from the CLI entry point entirely rather than forced into
an ambiguous shape; `session.start()`'s own `repository_id` kwarg is
untouched for internal/test callers. `Session.start` is back to a
single `project_name` parameter.

**`templates/build.py` added, so doc drift gets caught mechanically
instead of by hand.** Every manual doc sweep this session kept finding
*more* dead commands than the one being fixed (`main`/`sub`/`subs`,
`killservers`, `get project`/`memory`/`todo`, and a first pass over
every template turned up `touched`, `get opencode`, `ctx-template`,
`f`/`f tstop`/`f estop`, `get agents`/`get input`/`get output`,
`update-home` too) — clear sign the problem needed a tool, not another
pass. `verify()` regex-extracts every backtick `owrap ...`/`~/bin/owrap
...`/`{{BIN_DIR}}/owrap ...` span across `templates/**/*.md`, reduces it
to its fixed (non-placeholder, non-flag) token prefix, and resolves it
through the real `_resolve_kind_first` + `getattr(instance, action)` --
the same path the CLI itself takes, so it can't drift from the real
grammar by construction. Two real bugs surfaced building it: the
command regex matching `owrap_runner_enabled` (a config key, not a
command) because `owrap` is a prefix of it with no word-boundary check;
and `Daemon.get` being flagged unsupported because it only exists as
`_default_get` (the zero-args hook `dispatch()` calls instead of the
public method) -- both fixed, covered in
`tests/test_revised_doc_build.py`. `generate()` rewrites a marked
GENERATED block in `self/commands.md` with a full per-kind reference
built straight from `KIND_REGISTRY`'s `usage` dicts, so that table
can't go stale either. Wired in at one point only: `deploy.py`'s
`validate_source` runs `build.py --check` (verify-only, no write) and
raises before promotion -- the hard gate dev→live. Deliberately not
wired into `owrap sync`: that's routine per-session staging and
shouldn't fail (or silently rewrite a committed file) over a docs
issue elsewhere in the tree.

**Every stale command `--check` found got fixed, not just catalogued.**
Two were real gaps, not just renames: `Ctx.template` was wired up (the
underlying `owrap/ctx/manual.py::template()` already existed in full,
just never exposed as a `Ctx` action -- `owrap ctx template
[subproject]` now works, matching `CLAUDE.md`'s own Planner Working
Manual's `--ctx manual` fallback, which depended on the exact dead
name); `Self.get("output", <msg|task|agent|exec>)` was added (latest
output path + preview, reusing `session_exec_output_path`/
`session_agent_log_path`/`session_msg_output_dir`/
`session_task_output_dir` -- a specific id was already covered by
each dispatch kind's own `get <id>`, so `Self` only needed the
latest-without-an-id case). The rest were pure doc staleness with a
real command already working under a different name: `owrap touched`
→ `owrap ctx add`, `owrap get opencode` → `owrap self get opencode`,
`owrap f`/`f tstop`/`f estop` → `owrap fallback start`/`fallback done
task`/`fallback done exec`, `owrap get agents` → `owrap agent get`
(bare, zero-arg digest), `owrap get input` → `owrap self get input`,
`owrap update-home` → `owrap update do <path>` (note the explicit
`do` -- `Update` isn't a `Dispatch` kind, so a bare non-action token
isn't reinterpreted the way it is for `read`/`task`/etc). Also found
by hand, not by the tool: `owrap ctx`/`owrap updr` used bare (no
action word) in several places -- runs, but only ever hits the base
`Actions.do`, which unconditionally raises, so it prints help then
errors instead of doing anything; fixed to the explicit `ctx start`/
`updr start`. Tried teaching `build.py` to catch that class
automatically (flag any bare kind mention where the kind doesn't
override `do`), but reverted it -- it also fired on every section
header in its own generated appendix (`` ### `owrap backup` ``) and
on label-style mentions (`` **Reads (`owrap read`):** ``), which are
not invocation examples at all; the false-positive rate wasn't worth
it for a case manual review already caught. `--check` now passes
clean against the real checkout.

**`self/commands.md`'s hand-written tables trimmed once the generator
existed to make them redundant on exact syntax.** Each `Command`
column cell was trimmed to its fixed (non-placeholder) token prefix
only -- `owrap project start <id>` → `owrap project start` -- since
full args/flags now live in the one generated appendix and arg-shape
drift was exactly what kept slipping through hand-maintained syntax.
Literal keyword branches that distinguish two different `Effect` rows
(`session add temp` vs `session add`) were kept; pure variable
placeholders were dropped. Configuration/Troubleshooting/Duration
defaults/Exit codes stayed fully hand-written -- not kind/action
syntax, nothing for the generator to own.

**`Self.get("runtime"/"history")` added, and `cli.py` now logs
`cmd.start`/`cmd.end` to rtlog on every invocation.** Ported from the
live `owrap/commands/get.py::run_runtime`/`run_runtime_history`
(found by reading the live checkout directly, not guessed at): a
real gap existed where the new `cli.py` never wrote to rtlog at all,
so there was no record of what commands actually ran, only the
internal dispatch/server/daemon mechanics. `runtime` tails the raw
log (filtered by `--sid`/`-g`, reusing the existing grep flag rather
than inventing a prefix-match convention); `history` (or `runtime
history`) pairs `cmd.start`/`cmd.end` by pid and shows each
completed command with its argv. Verified in
`tests/test_self_runtime.py`.

**`cmd.end` extended with a success/failure snippet, and `history`'s
line format reordered to match `work.format_task_status`'s
convention.** Previously `cmd.end` only had `rc`/`dur_s` -- no record
of *why* a command failed or what a successful one actually did.
Added `error` (the exception text) on failure and `result`
(`dispatch()`'s returned message) on success, both passed through
the new `oneline()` helper. Deliberately left `SystemExit` (from
`_usage()`'s own `sys.exit(2)`) uncaught, per explicit choice --
usage errors stay unlogged rather than risk interfering with the
exit flow. `history` prints `error:`/`result:` lines under each
entry when present, and its per-entry line now reads `cmd  status
dur  @ ts  [sid]` instead of `cmd  [sid]  status  dur  @ ts`, closer
to how `owrap stat` already renders task lines elsewhere.

**`oneline()` added to `owrap/utils/parser/text.py`** (collapse to
one line, truncate with `…`) rather than defined locally in
`cli.py` -- the single-line-truncate shape didn't already exist
there (`preview` trims by word count, not a hard char limit), and it
belongs with the module's other generic text-formatting helpers for
reuse. Verified in `tests/test_text.py`.

**`test_revised_*.py` renamed to `test_*.py` across the board, and
the now-meaningless `revised` pytest marker dropped from `pytest.ini`
and every file's `pytestmark`.** The prefix only ever meant "part of
the new kind-first rebuild, as opposed to the old system" -- now that
the old system lives in `tests_old/` (never collected) and the new
one is simply *the* test suite, the distinction serves nothing.
Historical mentions of the old filenames earlier in this log are left
as-is; they're accurate to what existed at the time.

## Style

Every file here follows `docs/style.md` exactly, not just "looks about
right" — check each new/edited file against it specifically before calling
it done:

- **Method ordering** inside a class: public methods, then `# Private
  Methods`, then `# Class Methods`/`# Static Methods` (grouped,
  classmethod/staticmethod last) — each section heading gets two blank
  lines before it and one after.
- **Imports**: stdlib → third-party → local, one blank line between
  groups; no wildcard imports.
- **Docstrings**: required on public classes and non-trivial public
  methods; state what it does, not why, and never compare it to another
  file/function. Trivial one-line stubs (a raise, a `pass`) skip the
  docstring.
- **Comments**: one line, non-obvious logic only; no `---`/`===` dividers
  anywhere.
- **Line length**: 90 chars max — check with, e.g., `awk 'length>90' <file>`
  after every edit, not just at the end.
