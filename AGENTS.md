# owrap development checkout

- Work on owrap code only in `/home/humble/marl/owrap-dev`. Treat `/home/humble/marl/owrap` as the live, read-only checkout during development.
- Do not edit, format, test, or run setup from the live checkout. A deployment is a separate, explicit task after a dev commit has been tested.
- Run dev commands through `/home/humble/marl/owrap-dev/files/bin/owrap`. The normal `owrap` command runs live code and uses live state.
- Run pytest from this checkout with `/home/humble/e-swarm/bin/python3 -m pytest`. Tests create private state under `files/test-runs`; dev operational state is under `files/state`.
- Keep dev workspaces, logs, scratch state, and deployment artifacts under `owrap-dev/files`. Do not put them in `/home/humble/marl` or the live checkout.
- Before editing, check `pwd` and `git status --short --branch`. The working branch must be `dev`. Preserve existing uncommitted changes.
- The migration working list is `files/workspace/docs/research/todo/owrap.md`; the target project and repository layout is in `MEMORY_SCHEMA.md`. Work through the open migration items in order and keep the live research files unchanged.
