## Quick Commands

| Command | What it does |
|---|---|
| `oread -f <file> [-s] [-d "..."]` | Read any file, verification, one-shot query. Streams output inline. |
| `orun --msg "..."` | Short inline task. Foreground. |
| `orun` | File task: reads `input.md`, dispatches `task<N>.md`. Auto-backgrounds + `owait run`. |
| `oexec` | Execute active plan. Auto-backgrounds + `owait exec`. |

## Parallel Execution

`orun` (file task) and `oexec` auto-background and call `owait run`/`owait exec` internally. Use `--fg` to force foreground. `orun --msg` is always foreground. `oread` is always foreground.

## TODO
