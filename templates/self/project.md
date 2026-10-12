# Project file template

Create the project directory at `{{DOCS_ROOT}}/projects/<project>/`.
The project ID is the directory and YAML basename. Link repositories by their
registered IDs. Add subproject entries only when the corresponding Markdown
files exist.

## `<project>.yaml`

```yaml
schema_version: 1
kind: project
id: example-project
title: Example Project
main: main.md
repositories: [example-repo]
subprojects: {}
```

`subprojects` maps each subproject ID to its `kind`, `file`, and `parent`.
The parent is `main` or another subproject ID. Parents must exist and may
not form cycles. An optional `repositories` list overrides inherited links.

## `main.md`

```markdown
# Example Project

## Overview

What this project aims to achieve and its scope.


## Goals

- [ ] One actionable outcome.


## Status

Current state and blockers.


## Decisions

- YYYY-MM-DD — Decision and reason.


## Notes

User-owned notes.
```

Goals have open or done checkboxes. `Status` describes the current state;
completed work belongs in decisions or Git history. `Notes` is user-owned:
automated updates must preserve it. Keep execution steps in the session plan.

## Scratch notes

`owrap add project scratch` creates a disposable design/architecture
notes file for the active target -- `scratch.md` for the project root,
or `<subproject>.scratch.md` for a selected subproject. It is never
listed in `subprojects` and never touched by `ctx`/`updr`: it exists
purely for the user and the planner to think out loud in, and either
may edit or `owrap clear project scratch` it freely. Durable goals,
status, and decisions still belong in `main.md`/the subproject file,
not here.
