# Sessions

Sessions keep working context separate from durable project and repository
records. A session may target a project root, a subproject, or a repository.
Multiple sessions may target the same record without sharing their plans.

## OWRAP_HOME

`{{OWRAP_HOME}}` resolves from `$OWRAP_HOME`, then `~/.owrap_home`, then
`~/.owrap`. `owrap update-home <path>` changes the pointer; `--migrate`
relocates existing runtime state. Test work uses its own development home.

## Session files

Every session has a lookup record at
`{{OWRAP_HOME}}/sessions/<session-id>.session`. It stores identity, target,
parent session, and mode. Working files live under
`{{OWRAP_HOME}}/sessions/<session-id>/`:

| File | Role |
|---|---|
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

`owrap start --project <id> [--subproject <id>]` targets a project node.
`owrap start --repository <id>` targets a repository alone. `owrap attach
<session-id>` binds the current window to an existing session. Attaching does
not change its target.

`owrap spawn [name]` creates a child session with its parent's target and
repository links. It records `parent_session_id` and creates no checkout.
`owrap temp [name]` creates a standalone session with no required target or
parent. If unnamed, it receives `temp-<session-id>`. Its files use the normal
session paths above.

## Branch sessions

`owrap branch [name] [--ref <git-ref>]` creates a child session and one Git
worktree per associated repository at
`<workspace>/branches/<session-id>/<repository>/`. The source checkouts must
be clean. A branch session records each source checkout, base ref and commit,
worktree path, and branch ref.

`owrap branch merge [--session <id>] [--repo <id>]` previews code changes.
Pass `--apply` to merge. A branch with several repositories requires a
separate `--repo` merge for each one. After code merge, collapse the session;
then `owrap branch cleanup --session <id> --apply` removes clean, merged
worktrees and refs. Spawn and temp sessions make no branch folders.

## Collapse

`owrap collapse [--session <id>]` previews new child context entries.
`--apply` copies those entries into the parent context and marks the child
collapsed. It preserves the parent's active focus. Branch sessions require
code merge first. A temp session has no parent and cannot be collapsed.
