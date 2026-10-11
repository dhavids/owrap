"""
`_print_context_jobs` must render a failed job distinctly from a
real success, not both under the same "done(...)" label.
"""
from owrap.kind.op.stat import _print_context_jobs


def test_failed_job_prints_failed_not_done(capsys):
    _print_context_jobs([{
        "status": "failed", "rc": 1, "kind": "auto", "session_id": "sid1",
        "job_id": "abc123", "started": 0, "finished": 10,
    }])
    out = capsys.readouterr().out
    assert "failed(rc=1)" in out
    assert "done(rc=1)" not in out


def test_succeeded_job_still_prints_done_ok(capsys):
    _print_context_jobs([{
        "status": "succeeded", "rc": 0, "kind": "auto", "session_id": "sid1",
        "job_id": "abc123", "started": 0, "finished": 10,
    }])
    out = capsys.readouterr().out
    assert "done(ok)" in out
