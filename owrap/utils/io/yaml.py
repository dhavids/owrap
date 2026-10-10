import time
from pathlib import Path

from .atomic import write_atomic
from .filelock import file_lock


def touch_last_updated(yaml_path: Path) -> float:
    """
    Bump a YAML record's `last_updated` field to now and write it back
    out, returning the timestamp written (or the current time if the
    record couldn't be read -- this never raises).
    """
    now = time.time()
    with file_lock(yaml_path.with_suffix(".yaml.lock")):
        try:
            import yaml
            record = yaml.safe_load(yaml_path.read_text())
        except Exception:
            return now
        if not isinstance(record, dict):
            return now
        record["last_updated"] = now
        content = yaml.safe_dump(record, sort_keys=False, allow_unicode=True)
        write_atomic(yaml_path, content)
    return now
