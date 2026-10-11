"""
`sweep_old` (called automatically from `finish()`) must actually
delete a job's directory from disk, not just filter it out of
`context_jobs.recent()`'s display -- confirming that needs a real
run, not a read of the code.
"""
import json
import time

from owrap.utils.log import context_jobs


def test_sweep_old_removes_a_job_finished_past_the_age_threshold(tmp_path):
    job_dir = context_jobs.create("sidA", "ccsidA", "auto")
    context_jobs.finish(job_dir, 0)
    # Back-date the finish time so it reads as already past the threshold.
    data = context_jobs.get(job_dir.name)
    stale = {**data, "finished": time.time() - 100}
    (job_dir / "status.json").write_text(json.dumps(stale))

    removed = context_jobs.sweep_old("sidA", older_than_s=30)

    assert removed == 1
    assert not job_dir.exists()


def test_sweep_old_keeps_a_recently_finished_job(tmp_path):
    job_dir = context_jobs.create("sidB", "ccsidB", "auto")
    context_jobs.finish(job_dir, 0)

    removed = context_jobs.sweep_old("sidB", older_than_s=30)

    assert removed == 0
    assert job_dir.exists()


def test_finish_sweeps_this_sessions_old_jobs_automatically(tmp_path):
    old_job = context_jobs.create("sidC", "ccsidC", "auto")
    context_jobs.finish(old_job, 0)
    data = context_jobs.get(old_job.name)
    stale = {**data, "finished": time.time() - context_jobs.JOB_SWEEP_AGE_S - 1}
    (old_job / "status.json").write_text(json.dumps(stale))

    new_job = context_jobs.create("sidC", "ccsidC", "auto")
    context_jobs.finish(new_job, 0)

    assert not old_job.exists()
    assert new_job.exists()
