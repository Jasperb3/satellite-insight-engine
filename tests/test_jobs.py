"""Background-job lifecycle for the live-progress + cancel flow (E1/E2)."""

import threading
import time

import pytest

from satviz.application.jobs import JobManager
from satviz.engine import AnalysisCancelled, SatVizEngine
from satviz.models import ImageResult, Location


def _wait(job, state, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if job.state == state:
            return True
        time.sleep(0.01)
    return False


def test_job_runs_to_completion_and_reports_stages():
    jm = JobManager()
    seen = []

    def worker(on_stage, should_cancel):
        on_stage("imagery")
        on_stage("vision")
        return "RESULT"

    job = jm.get(jm.start(worker))
    assert _wait(job, "done")
    assert job.result == "RESULT"
    # The final stage seen by the manager is recorded on the job.
    assert job.stage == "vision"
    del seen


def test_job_records_error():
    jm = JobManager()

    def worker(on_stage, should_cancel):
        raise RuntimeError("boom")

    job = jm.get(jm.start(worker))
    assert _wait(job, "error")
    assert "boom" in job.error


def test_job_cancellation_marks_cancelled():
    jm = JobManager()
    started = threading.Event()

    def worker(on_stage, should_cancel):
        on_stage("vision")
        started.set()
        while not should_cancel():
            time.sleep(0.01)
        raise AnalysisCancelled()

    job = jm.get(jm.start(worker))
    assert started.wait(2.0)
    assert jm.cancel(job.id) is True
    assert _wait(job, "cancelled")


def test_cancel_unknown_job_returns_false():
    assert JobManager().cancel("nope") is False


def _engine_no_storage():
    eng = SatVizEngine.__new__(SatVizEngine)  # skip Storage() construction
    eng.storage = None
    return eng


def test_engine_raises_when_cancelled_before_vision():
    img = ImageResult(location=Location(0.0, 0.0, "x"), buffer=1500, image_path="foo.jpg")
    with pytest.raises(AnalysisCancelled):
        _engine_no_storage()._analyze(img, should_cancel=lambda: True)
