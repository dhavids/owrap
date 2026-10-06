# Recovery

## Context recovery

If a session's `context.md` is missing, run `{{BIN_DIR}}/owrap refresh` for
that session. If a required section is missing, restore the headings listed
in [Context](context.md#context-file) before resuming context updates.


## Decision pruning

Review a project's current `## Decisions` before removing entries. A later
decision may supersede an older one; a cited path may have moved. Verify the
current code and repository record, then remove only confirmed duplicates or
obsolete entries. Preserve the user's `## Notes`. Keep a Git commit or backup
before pruning durable project files.


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
