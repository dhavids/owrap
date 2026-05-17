# AGENTS.md

This file provides guidance when working with code in this repository.

## Agent Modes

| Command | Mode | What it does |
|---|---|---|
| `--executor` (default) | Executor | Execute active plan steps |
| `--planner` | Planner | Design/update research roadmap |
| `--check` | Planner review | Verify completed work |
| `--exec` | Executor shortcut | Cold-start and execute active plan |

## Cold-Start Sequence (Executor)

Read `self.md` → read `plan.md` for `[ACTIVE]` block → read corresponding `projects/<research>.md` → read `memory.md` → execute steps → update `docs/changes/`, `memory.md`, mark TODOs `[x]`.

## Dispatch Rules

*(document dispatch conventions here)*
