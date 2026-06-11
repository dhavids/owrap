# How to Run owrap Tests

## Unit tests (pytest)

```bash
cd /home/humble/marl/owrap
python3 -m pytest tests/ -v
```

Before running, all servers and running tasks are killed automatically (session-scoped autouse fixture). They are also killed after the suite finishes.

All output directories are redirected to `tmp_path` per test — nothing is written to the live `~/.owrap/` state.

### Coverage summary

| File | Tests | What it covers |
|------|-------|----------------|
| `test_manager.py` | 7 | Manager state, task registration, completion |
| `test_run.py` | 5 | RunRunner msg validation, task mode, fallback |
| `test_exec.py` | 3 | ExecRunner plan dispatch, fallback |
| `test_read.py` | 4 | ReadRunner file + grep modes |
| `test_pool.py` | 6 | pool active check, shutdown_idle, update_last_used, trim_logs |
| `test_watchdog.py` | 5 | stall notify, healthy reset, kill after delay, stop cancels, sentinel health |
| `test_logger.py` | 4 | file handler creation, prune keeps max, prune noop, prune called on init |
| `test_paths.py` | 7 | context_path, context_lock_path, get_plan_path, session_log, SERVER_LOGS_DIR, TASK_LOGS_DIR, PLANS_DIR |

---

## Integration smoke tests (manual)

### 1. oread — inline file queries

```bash
oread -f tests/md/test_read.md -d "list all bash commands shown in this file"
oread -f ../../docs/research/self.md -s
oread -f owrap/manager.py -d "what does _housekeeping do and what files does it clean up?"
```

No session state required. Output is inline.

### 2. orun — short message task (foreground)

```bash
orun --msg "run date in bash and print the current timestamp"
```

Completes in ~15–30s. Writes a one-line entry to `docs/run/log_<session>.md`.

### 3. orun — file task (background + owait)

```bash
SESSION=$(grep "^session_id=" ~/.owrap/sessions/${CLAUDE_CODE_SESSION_ID}.session | cut -d= -f2)
cp owrap/tests/md/test_task.md ~/.owrap/docs/run/tasks/input_${SESSION}.md
orun
```

### 4. oexec — plan execution (background + owait)

```bash
SESSION=$(grep "^session_id=" ~/.owrap/sessions/${CLAUDE_CODE_SESSION_ID}.session | cut -d= -f2)
cp owrap/tests/md/test_plan.md ~/.owrap/docs/exec/plans/plan_${SESSION}.md
oexec
```

### Checking results

```bash
owrap stat
cat ~/.owrap/docs/exec/log.md
cat ~/.owrap/docs/run/log.md
```
