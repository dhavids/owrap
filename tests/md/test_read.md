# oread Test Fixture

A reference file for verifying oread works. Run each command from the repo root.

## Test calls

### 1. Read this file with a targeted question (fast sanity check)
```bash
oread -f tests/md/test_read.md -d "list all bash commands shown in this file"
```

### 2. Summarise self.md (longer read, verify research file is accessible)
```bash
oread -f ../../docs/research/self.md -s
```

### 3. Targeted query on manager.py
```bash
oread -f owrap/manager.py -d "what does _housekeeping do and what files does it clean up?"
```

> All paths are relative to the `owrap/` directory (oread shim cds there before running).

## Expected behaviour

Each call prints output inline (foreground, ~10s). No log entry is written.
`oread` never modifies any file.
