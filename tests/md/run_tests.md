# How to Run owrap Tests

Tests belong to the `dev/owrap` checkout and refuse to import owrap from any
other checkout.

```bash
cd /home/humble/marl/dev/owrap
/home/humble/e-swarm/bin/python3 -m pytest tests/ -m "not runner" -v
```

The suite creates a private `OWRAP_HOME` under `files/test-runs`, directs
per-test state to pytest temporary directories, and uses server ports starting
at 15096. It clears inherited session identifiers and does not invoke global
server cleanup, so live owrap sessions and servers remain untouched.

The `runner` marker covers dispatch/server-lifecycle tests (`orun`, `oexec`,
`owrap f`, `oagent`, daemon, pool, watchdog); they currently hang when run as
a group (real daemon/server processes not torn down between tests — open
issue, not permanently routed around) and should stay excluded with
`-m "not runner"` until fixed.

For an isolated command smoke test, use the development launcher explicitly:

```bash
/home/humble/marl/dev/owrap/files/bin/owrap stat
```

Normal commands under `/home/humble/bin` use the live checkout and are outside
the test environment.
