# Project and repository memory schema

This is the target layout for the project/repository memory migration. Paths below
are relative to the configured `research_root`. Existing `projects/<research>.md`,
`memory/<research>.md`, and `todo/<research>.md` remain readable until the reviewed
migration and command routing are complete.

## Identity and paths

```
projects/<project>/<project>.yaml
projects/<project>/main.md
projects/<project>/<subproject>.md
repositories/<repository>/<repository>.yaml
repositories/<repository>/main.md
```

`project`, `subproject`, and `repository` are stable, case-sensitive slugs. Each
slug uses lowercase ASCII letters, digits, and hyphens; it begins with a letter
or digit. A project owns its subproject slugs. Repository slugs are unique across
the research root. Display titles can change without renaming identities or
files. File paths in YAML are relative to `research_root`; checkout paths in
repository YAML are absolute. No command should infer a parent by splitting a
slug on a hyphen.

`projects/<project>/<project>.yaml` is the machine-readable identity and link
record. Its minimum fields are `schema_version: 1`, `kind: project`, `id`,
`title`, `main: main.md`, `repositories: []`, and `subprojects: {}`. Each entry
under `subprojects` has `kind: regular|branch`, `file: <slug>.md`,
`parent: main|<subproject>`, and `repositories: []`. A branch entry also has
`branch_repository` and `branch_ref`; `branch_repository` must appear in its
effective repository association. A branch's `parent` is explicit and must
refer to an existing project node. No cycles are allowed. `main` is the
project root node and is not itself a subproject. A subproject's effective
repositories are its own list if present, otherwise its parent's, then the
project's list. An empty list explicitly means no repository association.

`repositories/<repository>/<repository>.yaml` has `schema_version: 1`,
`kind: repository`, `id`, `title`, `main: main.md`, `checkout`, and optional
`remote`. The `checkout` is an exact local path, never a search hint. The same
repository record can be linked from several projects, so its architecture is
written once. A repository-only session points to this record without a
project. Project and repository IDs have separate namespaces; a session stores
the kind of target, never guesses it from a matching name.

Example:

```yaml
schema_version: 1
kind: project
id: owrap
title: owrap
main: main.md
repositories: [owrap]
subprojects:
  memory-migration:
    kind: regular
    file: memory-migration.md
    parent: main
    repositories: [owrap]
  memory-migration-trial:
    kind: branch
    file: memory-migration-trial.md
    parent: memory-migration
    repositories: [owrap]
    branch_repository: owrap
    branch_ref: trial/memory-migration
```

## Markdown ownership

`projects/<project>/main.md` owns the project overview, desired outcomes,
current project-wide goals, current status, decisions, and notes. Its headings
are `# <title>`, `## Overview`, `## Goals`, `## Status`, `## Decisions`, and
`## Notes`. `## Goals` contains actionable goals, with open/done state; it is
the source for project goals. Plans and execution steps remain in session plan
files. `## Decisions` contains dated, durable decisions and their reasons.
`## Status` contains only current state and blockers; completed work belongs in
decisions or Git history. `## Notes` is user-owned and automated context updates
must not overwrite it.

Each `projects/<project>/<subproject>.md` has the same headings but covers only
that subproject. Its overview explains its scope and links to its parent. Goals,
status, decisions, and notes for that work live here rather than in project
`main.md`. A branch subproject records findings and unfinished goals here until
a reviewed merge into its parent; documentation merge is separate from Git
merge. A branch file is archived after its findings and goals are reconciled.

`repositories/<repository>/main.md` owns shared repository architecture:
components, paths, interfaces, configuration, build and test commands, and
durable technical constraints. Its headings are `# <title>`,
`## Architecture`, `## Components`, `## Interfaces`, `## Environment`, and
`## Notes`. It does not own project goals, progress, or decisions. A project
decision that changes a shared interface is recorded in the project decision
log and the resulting current interface is reflected in the repository file.
Relative code paths in this file are relative to the repository checkout.

YAML contains identity, relationships, and path pointers only. It does not
duplicate prose, goals, status, or architecture. Markdown links use relative
paths to the canonical records. A link is a reference, not a second copy of
the fact. When a project touches several repositories, each repository record
receives only its own architecture changes.

## Migration and update rules

- Existing `projects/<research>.md` `## Overview` maps to project `main.md`.
  Each old `## <area>` maps to one regular subproject file; `### Status` and
  `### Decisions` go to their corresponding headings. Preserve `### Notes`
  verbatim. Existing explicit `**Parent area:**` annotations become `parent`
  links; hyphens alone do not imply parentage.
- Existing `memory/<research>.md` architecture maps to the relevant repository
  `main.md`. An area with no known repository association is flagged for review,
  not assigned by name guessing. Duplicate shared facts are consolidated only
  after review.
- Existing `todo/<research>.md` open items become goals in the relevant
  project or subproject Markdown file. The migration preview must show each
  source item and destination, including completed items, before any write.
- Session identity changes are separate: a session stores `target_kind`,
  `project_id` and optional `subproject_id`, or `repository_id` for a
  repository-only session. Its `repositories` list records the associated
  repository IDs. Legacy `research` and `area` fields are retained during
  migration so existing sessions continue to resolve.
- Automated `ctx` and `updr` updates lock each destination, deduplicate new
  facts, and reject stale statements superseded by current records. They update
  current status and architecture in their respective files and never erase
  user-owned notes. A branch merge requires review of goals and decisions.
- The migration command must provide dry-run output, a backup, idempotent
  writes, and rollback before this layout becomes the default for commands.

This schema defines the destination. It does not switch command routing or
migrate the current live files by itself.
