"""
The `wait` action (owrap/actions/run/wait.py) and its concrete
overrides -- Session._on_wait (input-queue polling), Ctx._on_wait/
Updr._on_wait (background-job polling via ctx/dispatch.py's
wait_for_job) -- exercise real timing/polling loops, which reading
the code alone doesn't confirm: does the deadline math actually
time out, does a status change mid-poll actually get picked up.
"""
import json
import threading
import time

import pytest

from owrap.ctx.dispatch import wait_for_job
from owrap.kind.run.ctx import Ctx
from owrap.kind.run.session import Session
from owrap.kind.run.updr import Updr
from owrap.utils.log import context_jobs
from owrap.utils.paths import session_ctx_jobs_dir, session_input


def _write_job_status(session_id: str, job_id: str, **fields) -> None:
    job_dir = session_ctx_jobs_dir(session_id) / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "status.json").write_text(
        json.dumps({"job_id": job_id, "session_id": session_id, **fields}),
    )


# Session._on_wait (input-queue clear)

def test_wait_input_clear_when_no_input_file_exists(monkeypatch):
    monkeypatch.setenv("OWRAP_SESSION", "sess-a")
    result = Session()._on_wait()
    assert result == {"message": "input clear"}


def test_wait_input_picks_up_clear_mid_poll(monkeypatch):
    monkeypatch.setenv("OWRAP_SESSION", "sess-b")
    path = session_input("sess-b")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("queued instruction")

    def _clear_soon():
        time.sleep(0.3)
        path.write_text("")
    threading.Thread(target=_clear_soon).start()

    result = Session()._on_wait(timeout=5)
    assert result == {"message": "input clear"}


def test_wait_input_times_out_when_never_cleared(monkeypatch, capsys):
    monkeypatch.setenv("OWRAP_SESSION", "sess-c")
    path = session_input("sess-c")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stuck instruction")

    with pytest.raises(SystemExit) as exc:
        Session()._on_wait(timeout=0.2)
    assert exc.value.code == 2
    assert "timed out waiting for input to clear" in capsys.readouterr().out


# context_jobs.get (by-id lookup)

def test_context_jobs_get_finds_matching_job_by_id():
    _write_job_status("sess-d", "job123abc", status="succeeded")
    found = context_jobs.get("job123abc")
    assert found is not None
    assert found["status"] == "succeeded"


def test_context_jobs_get_returns_none_for_unknown_id():
    assert context_jobs.get("no-such-job-at-all") is None


# wait_for_job

def test_wait_for_job_returns_immediately_when_already_finished():
    _write_job_status("sess-e", "donejob", status="failed", rc=1)
    job = wait_for_job("donejob")
    assert job["status"] == "failed"
    assert job["rc"] == 1


def test_wait_for_job_picks_up_status_change_mid_poll():
    _write_job_status("sess-f", "slowjob", status="running")
    status_path = session_ctx_jobs_dir("sess-f") / "slowjob" / "status.json"

    def _finish_soon():
        time.sleep(0.3)
        status_path.write_text(json.dumps({
            "job_id": "slowjob", "session_id": "sess-f",
            "status": "succeeded", "rc": 0,
        }))
    threading.Thread(target=_finish_soon).start()

    job = wait_for_job("slowjob", timeout=5)
    assert job["status"] == "succeeded"


def test_wait_for_job_raises_for_unknown_id():
    with pytest.raises(ValueError, match="no such ctx job"):
        wait_for_job("totally-unknown-job")


def test_wait_for_job_times_out_on_a_job_that_never_finishes():
    _write_job_status("sess-g", "stuckjob", status="running")
    with pytest.raises(ValueError, match="timed out waiting for ctx job"):
        wait_for_job("stuckjob", timeout=0.2)


# Ctx._on_wait / Updr._on_wait

@pytest.mark.parametrize("kind_cls", [Ctx, Updr])
def test_on_wait_requires_job_id(kind_cls, capsys):
    with pytest.raises(SystemExit) as exc:
        kind_cls()._on_wait()
    assert exc.value.code == 2
    assert "Usage:" in capsys.readouterr().out


@pytest.mark.parametrize("kind_cls", [Ctx, Updr])
def test_on_wait_reports_finished_job(kind_cls):
    job_id = f"job-{kind_cls.__name__}"
    _write_job_status("sess-h", job_id, status="succeeded", rc=0)
    result = kind_cls()._on_wait(job_id)
    assert result == {"message": "succeeded (rc=0)"}


@pytest.mark.parametrize("kind_cls", [Ctx, Updr])
def test_on_wait_fails_cleanly_for_unknown_job(kind_cls, capsys):
    with pytest.raises(SystemExit) as exc:
        kind_cls()._on_wait("no-such-job")
    assert exc.value.code == 2
    assert "no such ctx job" in capsys.readouterr().out
