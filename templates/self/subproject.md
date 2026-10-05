# Subproject file template

A subproject is a durable part of one project. Its parent is explicit in the
project YAML. A child session is a separate session relationship; it does not
create a subproject file.

## Entry in `<project>.yaml`

```yaml
subprojects:
  example-feature:
    kind: regular
    file: example-feature.md
    parent: main
    repositories: [example-repo]
```

`repositories` is optional. Omit it to inherit from the parent. Use `[]` to
declare no linked repositories. The parent may be another subproject ID.
Do not infer parentage by splitting a hyphenated name.

## `<subproject>.md`

Place this file next to project `main.md` at
`{{DOCS_ROOT}}/projects/<project>/<subproject>.md`.

```markdown
# Example Feature

## Overview

Scope of this subproject. Parent: [Example Project](main.md).

## Goals

- [ ] One actionable outcome for this subproject.

## Status

Current state and blockers for this work.

## Decisions

- YYYY-MM-DD — Decision and reason.

## Notes

User-owned notes.
```

Keep this file scoped to the subproject. Shared repository architecture goes
in the linked repository record, and project-wide goals stay in `main.md`.
