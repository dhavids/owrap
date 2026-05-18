# How to Run owrap Tests

Portable test fixtures for verifying the owrap session system after `owrap start`.
All tests write results to `owrap/docs/tests/test_output.md` (newest at top).

---

## 1. oread — inline file queries (foreground, ~10s each)

Run any of the calls from `test_read.md` directly:

```bash
oread -f tests/md/test_read.md -d "list all bash commands shown in this file"
oread -f ../../docs/research/self.md -s
oread -f owrap/manager.py -d "what does _housekeeping do and what files does it clean up?"
```

> Paths are relative to the owrap/ directory (where the shim cds before running).

No session state required. Output is inline. Nothing is written to disk.

---

## 2. orun — short message task (foreground)

```bash
orun --msg "run date in bash and print the current timestamp"
```

Completes in ~15–30s. Writes a one-line entry to `docs/run/log_<session>.md`.

---

## 3. orun — file task (background + owait)

Copy the task spec to the session input file, then dispatch:

```bash
SESSION=$(grep "^session_id=" ~/.owrap/sessions/${CLAUDE_CODE_SESSION_ID}.session | cut -d= -f2)
cp owrap/tests/md/test_task.md owrap/docs/run/tasks/input_${SESSION}.md
orun
```

`orun` backgrounds the executor and blocks on `owait run` until the log entry appears.
Result is prepended to `owrap/docs/tests/test_output.md`.

---

## 4. oexec — plan execution (background + owait)

Copy the test plan to the active session plan path, then dispatch:

```bash
SESSION=$(grep "^session_id=" ~/.owrap/sessions/${CLAUDE_CODE_SESSION_ID}.session | cut -d= -f2)
cp owrap/tests/md/test_plan.md owrap/docs/plan_${SESSION}.md
oexec
```

`oexec` backgrounds the executor and blocks on `owait exec` until the exec log entry appears.
Result is prepended to `owrap/docs/tests/test_output.md`.

---

## 5. oexec foreground (useful for debugging)

```bash
SESSION=$(grep "^session_id=" ~/.owrap/sessions/${CLAUDE_CODE_SESSION_ID}.session | cut -d= -f2)
cp owrap/tests/md/test_plan.md owrap/docs/plan_${SESSION}.md
oexec --fg
```

---

## Checking results

```bash
owrap stat                                    # server + session health
cat owrap/docs/tests/test_output.md           # accumulated test results
cat owrap/docs/exec/log_${SESSION}.md         # exec call log
cat owrap/docs/run/log_${SESSION}.md          # run call log
```
