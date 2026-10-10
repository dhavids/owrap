"""
Generic JSON state-file read/write, shared by any single-file server
or task state (owrap's own `*.json` state files, keyed by caller-
supplied path -- no implicit location of its own).
"""
import json
import os
import tempfile


def read_state(path: str) -> dict | None:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def write_state(path: str, state: dict) -> None:
    dir_path = os.path.dirname(path)
    os.makedirs(dir_path, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f)
        os.rename(tmp_path, path)
    except Exception:
        os.unlink(tmp_path)
        raise
