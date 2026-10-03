# owrap development checkout

- Edit owrap code only in `/home/humble/marl/owrap-dev` on branch `dev`. The `/home/humble/marl/owrap` checkout is live and read-only during development.
- Use `/home/humble/marl/owrap-dev/files/bin/owrap` for dev operations; the normal `owrap` command uses the live checkout and live runtime home.
- Run tests from this checkout with `/home/humble/e-swarm/bin/python3 -m pytest`. Keep dev workspace and runtime files under `owrap-dev/files`.
- Check `pwd` and `git status --short --branch` before edits, and preserve existing uncommitted changes. Never promote from dev to live unless the user explicitly asks for promotion, even after a dev commit has been tested.
- Read `/home/humble/marl/docs/style.md` and follow it for code changes.
- Use `MEMORY_SCHEMA.md` for the migration target and `files/workspace/docs/research/todo/owrap.md` for its working checklist. Keep live research files unchanged.
