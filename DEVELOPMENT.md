# Live and development owrap

The two checkouts have fixed roles:

| Purpose | Path |
| --- | --- |
| Live checkout | `/home/humble/marl/owrap` (branch `live`) |
| Editable checkout | `/home/humble/marl/owrap-dev` (branch `dev`) |
| Dev commands | `/home/humble/marl/owrap-dev/files/bin` |
| Dev `OWRAP_HOME` | `/home/humble/marl/owrap-dev/files/state` |
| Dev workspace | `/home/humble/marl/owrap-dev/files/workspace` |
| Dev research files | `/home/humble/marl/owrap-dev/files/workspace/docs/research` |
| Dev release and rollback files | `/home/humble/marl/owrap-dev/files/deploy` |

Normal `owrap`, `orun`, `oexec`, `oread`, `owait`, and `oagent` commands in `/home/humble/bin` always run code from the live checkout. The live `OWRAP_HOME` remains `/mnt/hgfs/files/.owrap`. The dev `files/` directory is ignored by Git and contains its own state, hooks, and workspace files.

Use an explicit path for dev commands:

```bash
cd /home/humble/marl/owrap-dev/files/workspace
/home/humble/marl/owrap-dev/files/bin/owrap start marl-dev
```

The dev launcher selects the dev code and state, clears inherited session identifiers, and uses server ports starting at 5096. The live server starts at 4096. Run tests from the dev checkout with `/home/humble/e-swarm/bin/python3 -m pytest`. The test suite creates a separate temporary home under `owrap-dev/files/test-runs` before importing owrap, uses test ports starting at 15096, and never runs the global server cleanup. Its runtime log is separate from both live and dev operational logs.

Agents started inside `owrap-dev` read `AGENTS.md` or `CLAUDE.md` for the dev-only edit policy. When starting an agent from another directory, give it `/home/humble/marl/owrap-dev` as its working directory or include that path and the policy in its task. The current migration checklist is in `files/workspace/docs/research/todo/owrap.md`; its target layout is in `MEMORY_SCHEMA.md`. Both live code and live research files stay unchanged until deployment.

`owrap setup` configures a workspace. Do not run `python setup.py` from the dev checkout: it installs shared launchers into `~/bin` and edits `~/.bashrc`. Dev `owrap sync` can edit global `~/.claude/settings.json`; stage and install dev hooks only in the dev workspace.

## Deploy a tested version

Promotion from `dev` to `live` requires an explicit request from the user. A passing test suite, a good commit, or a completed migration todo does not authorize promotion.

1. Commit the intended changes on `dev`, test that commit with dev state and workspace, and record the current live commit for rollback. Check `owrap p`, setup, session start, and server startup in dev.
2. Build and test a release candidate under `owrap-dev/files/deploy` using the intended dev commit. Check the exact code and any launcher or hook template changes there. Do not use the live state for candidate tests.
3. When the candidate passes, bring that commit into the `live` branch in `/home/humble/marl/owrap`. Resolve and test any merge differences before updating live. Update shared launchers from the live checkout only if their templates changed.
4. Restart running owrap processes that need to import the new code. Smoke check `/home/humble/bin/owrap p --workspace marl` and a normal live command. The command name and installed path stay the same.
5. If needed, restore the recorded live commit and restart those processes. The previous live checkout and original launchers are retained under `owrap-dev/files/deploy`.

Keep edits and experiments in `owrap-dev`. Update `owrap` only for a tested deployment.
