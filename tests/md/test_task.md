## Do

Run the following commands in bash and collect their output:

1. `date +"%Y-%m-%d %H:%M:%S"` — current timestamp
2. `echo "OWRAP_SESSION=$OWRAP_SESSION"` — verify session env var is set
3. `echo "OWRAP_RESEARCH=$OWRAP_RESEARCH"` — verify research env var is set
4. `python3 --version` — Python version
5. `cd /home/humble/marl/owrap && /home/humble/e-swarm/bin/python -c "import owrap; print('owrap import OK')"` — verify owrap imports

Append results to `/home/humble/marl/owrap/docs/tests/test_output.md` under a new heading:
```
### orun task — <timestamp from step 1>
```

Create the file if it does not exist. Prepend (newest at top).

## Output

New section prepended to `/home/humble/marl/owrap/docs/tests/test_output.md`.
