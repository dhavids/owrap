# Recovery

## Context recovery

If a session's `context.md` is missing, run `{{BIN_DIR}}/owrap refresh` for
that session. If a required section is missing, restore the headings listed
in [Context](context.md#context-file) before resuming context updates.


## Decision pruning

Prune a target's `## Decisions` and, for a linked repository, its
`## Architecture`/`## Components`/`## Interfaces`/`## Environment` facts —
both grow unbounded between prunes; this is what keeps them bounded.

List removal candidates first, each with a one-line reason: a later entry
supersedes it, or a cited path or fact no longer matches the current code
and repository record. Verify every candidate before removing it — never
guess. Leave the most recent few entries alone; they can't be stale yet.
Preserve the user's `## Notes`. Keep a Git commit or backup before writing.

After pruning, add one new Decision noting what was removed and why, so the
prune itself has an audit trail. Check `{{DOCS_ROOT}}/instruction.md`'s
`## Self` section for any workspace-specific pruning rules and follow those
too.


## DO NOW

`#DO NOW` identifies a recovery action in an owrap response. Read the named
section in this reference and perform that action. Session counters live under
`{{OWRAP_HOME}}/sessions/` and are maintained by owrap.


## Fallback dispatch

If the server-backed runner is unavailable, `owrap f <path>` runs a task or
plan file directly. A filename containing `task` selects task mode; other
filenames select plan mode. The fallback writes output and status under
`{{OWRAP_HOME}}/docs/f/<task|exec>/`. The input file must already exist.

Use `owrap f tstop` or `owrap f estop` to stop the corresponding fallback.
Check its `status.json` for `running`, `stalled`, `done`, or `crashed` state.
