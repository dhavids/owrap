# Research System Reference

File-based research manager for multi-codebase MARL research. **Global reference**: session model, file structure, all agent modes, research/memory formats. Read on demand. Planner-specific behaviour, plan format, and context file format live in `CLAUDE.md`.

## Session Model

Every session calls `owrap start` at boot. Resolves session ID via `$SESSION_ID` env or `by_ccsid/$CLAUDE_CODE_SESSION_ID` pointer (mints new if neither). Writes `~/.owrap/sessions/${SESSION_ID}.session` (durable, survives Claude restarts) and `~/.owrap/sessions/by_ccsid/${CLAUDE_CODE_SESSION_ID}` pointer (1-1 window-to-session binding). Runtime paths are session-scoped (`plan_<id>.md`, `log_<id>.md`, `input_<id>.md`, `context_<id>.md`).

## File Structure

| File | Role | Path |
|---|---|---|
| `plan_<session_id>.md` | Active research plan (one `[ACTIVE]` block) | `~/.owrap/docs/plan_<session_id>.md` |
| `plan0.md` | Fallback plan for `--execf` without path | `~/.owrap/docs/plan0.md` |
| `task0.md` | Fallback task for `--taskf` without path | `~/.owrap/docs/run/tasks/task0.md` |
| `input_<id>.md` | Serialized dispatch queue (session-scoped) | `~/.owrap/docs/run/tasks/input_<id>.md` |
| `task<N>.md` | Numbered task files for parallel hires | `~/.owrap/docs/run/tasks/task<N>.md` |
| `context_<id>.md` | Session context (auto-managed) | `~/.owrap/docs/context_<id>.md` |
| `CLAUDE.md` | Claude Code wrapper + planner working manual | `{{WORKSPACE}}/CLAUDE.md` |
| `self.md` | This file — global reference | `{{RESEARCH_ROOT}}/self.md` |
| `AGENTS.md` | Executor working manual | `{{WORKSPACE}}/AGENTS.md` |
| `memory/<research>.md` | Per-project memory | `{{RESEARCH_ROOT}}/memory/<research>.md` |
| `projects/<research>.md` | Per-research overview, phases, environment | `{{RESEARCH_ROOT}}/projects/<research>.md` |
| `{{CHANGES_DIR}}/<codebase>.md` | Per-repo changelogs (executor writes) | `{{CHANGES_DIR}}/<codebase>.md` |

## Self-Modification (Opencode/Owrap)

When a plan edits owrap itself (`{{WORKSPACE}}/owrap/`, `~/bin/orun`, `~/bin/oexec`, `~/bin/owait`), skip `~/bin/oexec` — use `opencode run --dangerously-skip-permissions -- --execf <plan_path>` in foreground only.

## Research Instruction Files (`projects/<research>.md`)

One file per research goal. Required sections: **Overview**, **Phases**, **Artifact Map**, **Environment Setup**. Metadata header:

```yaml
---
research: translator
status: active
last_updated: 2026-05-18
current_phase: 2
venv: ~/e-swarm
---
```

Steps live in `plan_<session_id>.md`, not here.

## Project Memory Structure (`memory/<research>.md`)

```markdown
## <Research Name>

### Status
Current phase, checkpoint, last run.

### Progress
What works, what does not.

### Decisions
| Date | Decision | Reason |
|---|---|---|

### Blocked
- item — reason

### Future TODO
- item
```

---

## DONE

<!-- preserved across syncs: do not overwrite existing DONE entries; planner appends -->
