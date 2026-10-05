# Project and repository records

The configured memory root is `{{DOCS_ROOT}}`. Project and repository IDs
are stable lowercase slugs containing letters, digits, and hyphens. A slug
starts with a letter or digit. Display titles may change without renaming IDs.

## Record layout

```text
{{DOCS_ROOT}}/
  projects/<project>/<project>.yaml
  projects/<project>/main.md
  projects/<project>/<subproject>.md
  repositories/<repository>/<repository>.yaml
  repositories/<repository>/main.md
```

The YAML files contain identity, links, and paths. Markdown files contain the
human-readable goals, decisions, and architecture. File references in YAML
are relative to the memory root; repository `checkout` paths are absolute.

## Record templates

- [Project](project.md): project YAML and project root Markdown.
- [Subproject](subproject.md): a project YAML entry and a subproject Markdown
  file. Its parent is explicit, including for nested subprojects.
- [Repository](repository.md): repository YAML and shared architecture Markdown.

The project root is `main`, not a subproject. A subproject inherits its
parent's repository associations unless its own YAML entry supplies
`repositories`; an explicit empty list means no repositories. One repository
may be linked from several projects while keeping a single architecture file.
Never infer a parent or repository link from a name or path.

## Ownership

Project and subproject files own goals, current status, dated decisions, and
user notes. Repository files own current shared architecture and interfaces.
Session files own temporary focus, context, plans, and execution output.
When a project decision changes an interface, record the decision in the
project and the current interface in the repository file.

Read [Sessions](sessions.md) for how a session points to these records and
[Context](context.md) for update behavior. Existing research and area files
remain readable during migration. Review a source-to-destination preview
before moving their content into these records.
