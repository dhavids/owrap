# Repository file template

Create a single record at
`{{DOCS_ROOT}}/repositories/<repository>/` for each checkout. Several
projects may link to it; they do not copy its architecture into their files.

## `<repository>.yaml`

```yaml
schema_version: 1
kind: repository
id: example-repo
title: Example Repository
main: main.md
checkout: /absolute/path/to/example-repo
```

`checkout` is the exact local Git checkout root. `remote` is optional. Paths
in the Markdown below are relative to this checkout.

## `main.md`

```markdown
# Example Repository

## Architecture

Current system shape and durable constraints.

## Components

- `src/module.py` — Role of this component.

## Interfaces

Current public commands, APIs, and data contracts.

## Environment

Build, test, and configuration instructions.

## Notes

Repository-specific reference notes.
```

Project goals, progress, and decisions belong in project or subproject files.
Update this record when the current architecture changes, including when a
project decision changes a shared interface.
