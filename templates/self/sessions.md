# Sessions

Sessions keep working context separate from durable project and repository
records. A session may target a project root, a subproject, or a repository.
Multiple sessions may target the same record without sharing their plans.

## OWRAP_HOME

`{{OWRAP_HOME}}` resolves from `$OWRAP_HOME`, then `~/.owrap_home`, then
`~/.owrap`. `owrap update do <path>` changes the pointer; `--migrate`
relocates existing runtime state. Test work uses its own development home.


## Session files

Every session stores its lookup record and working files under
`{{OWRAP_HOME}}/sessions/<session-id>/`. The `.session` file stores identity,
target, parent session, and mode:

| File | Role |
|---|---|
| `.session` | Session identity and target metadata |
| `context.md` | Current session context |
| `exec/plan.md` | Session execution plan |
| `run/input.md` | Task dispatch input |
| `run/output/` | Task output and logs |
| `ctx/` | Per-window context update scratch files |

The session record uses `target_kind=project` with `project_id` and optional
`subproject_id`, or `target_kind=repository` with `repository_id`. The
`repositories` field stores associated repository IDs. `owrap stat` shows
`type: normal`, `spawn`, `branch`, or `temp` from `session_mode`.


## Create and attach

`owrap project start <id>` (or bare `owrap start <id>`) targets a project
node; `owrap project add <sub-id>`/`owrap project set [sub-id]` then select a
subproject within it. `owrap attach <session-id>` binds the current window to
an existing session. Attaching does not change its target.

`owrap session add [name]` creates a child session with its parent's target
and repository links. It records `parent_session_id` and creates no checkout.
`owrap session add temp [name]` creates a standalone session with no required
target or parent. If unnamed, it receives `temp-<session-id>`. Its files use
the normal session paths above.


## Branch sessions

`owrap worktree add [name] [ref]` creates a child session and one Git
worktree per associated repository at
`<workspace>/branches/<session-id>/<repository>/`. The source checkouts must
be clean. A branch session records each source checkout, base ref and commit,
worktree path, and branch ref.

`owrap worktree done [sid] [repo_id]` previews code changes. Add `apply` to
merge. A branch with several repositories requires a separate `repo_id` merge
for each one. After code merge, collapse the session; then `owrap worktree
clear [sid] apply` removes clean, merged worktrees and refs. Spawn and temp
sessions make no branch folders.


## Collapse

`owrap session done [sid]` previews new child context entries. Add `apply`
to copy those entries into the parent context and mark the child collapsed.
It preserves the parent's active focus. Branch sessions require code merge
first. A temp session has no parent and cannot be collapsed.
