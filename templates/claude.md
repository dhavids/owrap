# CLAUDE.md

This file provides guidance to Claude Code when working with this project.

You are always in **--planner** mode unless a different flag is specified.

## Quick Commands

| Flag | Mode | What to do |
|---|---|---|
| *(none)* or `--planner` | Planner | Design/update plans, add project TODOs |
| `--executor` / `--exec` | Executor | Read `[ACTIVE]` plan → execute → mark TODOs `[x]` |
| `--check` | Planner review | Verify completed TODOs against plan |
| `--agent` | Planner + auto-dispatch | Plan → delegate via oread/orun/oexec → verify |
| `--task` | Task executor | Contract-driven task execution |

**Hire-first rule:** Delegate any non-thinking work via:
- `oread -f <file>` — file reads, verifications
- `orun --msg "..."` or `orun` — file writes, code edits, shell commands
- `oexec` — multi-step plan execution

## Dispatch Rules

*(document foreground/background dispatch conventions here)*

## Self-Modification Rule

*(document how to handle self-modifying code changes here)*
