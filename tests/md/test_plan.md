## [ACTIVE] owrap-smoke — owrap oexec smoke test
**Research:** opencode_helper
**Created:** 2026-05-18

### Steps

1. Run `date +"%Y-%m-%d %H:%M:%S"` in bash. Note the timestamp.
2. Run `cd /home/humble/marl/owrap && /home/humble/e-swarm/bin/python -c "import owrap; print('owrap import OK')"` in bash.
3. Run `cd /home/humble/marl/owrap && /home/humble/e-swarm/bin/python -m owrap.runner stat` in bash to get session status.
4. Prepend a new section to `/home/humble/marl/owrap/docs/tests/test_output.md` (newest at top):
   ```
   ### oexec plan — <timestamp from step 1>
   - import: <result of step 2>
   - stat: <condensed one-line summary from step 3>
   ```
   Create the file if it does not exist.
