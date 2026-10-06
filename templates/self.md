# Owrap reference

This file is the entry point for owrap's workspace reference. Read the page
in `self/` for the work you are doing. The configured documentation root is
`{{DOCS_ROOT}}`.

## Session Model

Read [Sessions](self/sessions.md) for normal, child, branch, and temporary
sessions, their paths, and their project or repository targets.


## OWRAP_HOME

Read [Sessions](self/sessions.md#owrap_home) for home resolution and session
files. Session context and plans live under `{{OWRAP_HOME}}/sessions/`.


## File Structure

Read [Sessions](self/sessions.md#session-files) for runtime files, and
[Memory](self/memory.md#record-layout) for project and repository records.


## Project and Repository Files

Read [Memory](self/memory.md) for project YAML, project `main.md`, subproject
Markdown, repository YAML, and repository `memory.md` templates. These records
own durable goals, decisions, and architecture. Session plans stay in the
session directory.


## Formatting

Every Markdown file under `templates/` and every record or session file it
produces follows the same section spacing. Leave exactly one blank line
between a heading and the text or list below it. Leave exactly two blank
lines between one `##` section's content and the next `##` heading. Leave
exactly one blank line between one `###` subsection and the next, and
between a `###` heading and its own text. Do not add blank lines anywhere
else — no leading or trailing blank lines, no extra gaps inside a section.


## Context File Format

Read [Context](self/context.md#context-file) for session context sections.


## Update Context

Read [Context](self/context.md#update-context) for `owrap ctx` and automatic
context updates.


## Update Protocol

Read [Context](self/context.md#update-records) for updates to project and
repository records.


## Context Recovery

Read [Recovery](self/recovery.md#context-recovery).


## Decision Pruning

Read [Recovery](self/recovery.md#decision-pruning).


## Collapse

Read [Sessions](self/sessions.md#collapse) for child session collapse.


## Child Areas

Older instructions use this name. New child work uses a child session; read
[Sessions](self/sessions.md#create-and-attach). Durable project scope uses an
explicit subproject record; read [Subproject](self/subproject.md).


## DO NOW Mechanism

Read [Recovery](self/recovery.md#do-now).


## Fallbacks

Read [Recovery](self/recovery.md#fallback-dispatch).


## Command Reference

Read [Commands](self/commands.md) for the current CLI and dispatch commands.


## Duration defaults

Read [Commands](self/commands.md#duration-defaults).


## Exit codes

Read [Commands](self/commands.md#exit-codes).
