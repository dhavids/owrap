## Do

Run the following msg commands and record timing results for each:

1. `owrap run --msg "echo hello world"` — basic msg, verify baseline speed
2. `owrap run --msg "echo test_with_context"` — msg with inline context (default)
3. `owrap run --msg "echo test_no_context" --no-context` — msg without context header
4. `owrap run --msg "date +%s"` — msg that triggers bash tool use
5. `owrap run --msg "date +%s"` — same msg again, check for caching effect
6. Run in parallel:
   ```bash
   owrap run --msg "echo parallel_call_1" &
   owrap run --msg "echo parallel_call_2" &
   wait
   ```
   — verify pool distributes across servers
7. `sleep 60 && owrap run --msg "echo after_idle"` — verify keepalive prevents cold-start

For each call, capture:
- wall-clock time (from `time` prefix or `[timing]` block)
- model name in output header (e.g., `> build · deepseek-v4-flash-free`)
- whether inline context was injected (look for `[session:` header)
- any file read tool calls (look for `permission requested` or `Read X` lines)

All calls should complete in <10s. Parallel calls should have wall-clock time close to single call time (not 2× or 3×).

## Output

Timing summary printed to stdout.
