# Context and record updates

## Context file

Each session has `{{OWRAP_HOME}}/sessions/<sid>/context.md` with these
sections:

- `## Focus`: current task or direction.
- `## Active Plan`: a short view of the session plan.
- `## Key Locations`: paths useful to ongoing work.
- `## Decisions`: choices made in this session.
- `## Environment`: active tools, flags, and constraints.
- `## How To`: commands and techniques that worked.
- `## Frequent Files` and `## Recent`: automatically maintained activity.

Session context helps continuation. Durable project decisions and repository
architecture belong in their canonical record files.

## Update Context

`{{BIN_DIR}}/owrap ctx` queues a context update for the current window. The
context worker reads the new transcript excerpt, reports new facts, and owrap
merges them into `context.md`. The daemon also checks attached windows on its
configured interval. A precompaction hook may trigger the same update when
that integration is available for the agent host.

Use `owrap touched <path> [<path> ...] [--note <text>]` when an important file
change should be included in the next context pass. `owrap refresh` and
`owrap attach` show the last context update status.

## Update records

`owrap updr` updates durable records associated with the current session.
For a project target, goals, status, and decisions belong in its project or
subproject Markdown file. Shared architecture belongs in each associated
repository's `main.md`. An update must preserve user-owned `## Notes` and
must not infer an association from a name alone.

`owrap updr --ctx` requests a record and context update from one transcript
excerpt. Existing research and area routing remains during migration; use the
new project, subproject, and repository identity fields for new sessions.
