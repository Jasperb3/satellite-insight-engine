"""Background analysis jobs for the GUI's live-progress + cancel flow (E1/E2).

A snapshot runs ~2 minutes, so the request that starts it returns a job_id immediately;
the work runs on a daemon thread that reports its stage and watches a cancel flag. The web
layer polls status and can cancel. This stays UI-agnostic — no web-framework types here."""

import logging
import threading
import uuid
from dataclasses import dataclass, field
from time import time
from typing import Callable

logger = logging.getLogger(__name__)

# Keep finished jobs around briefly so the client can fetch the result/last status, then prune.
_RETAIN_SECONDS = 600


@dataclass
class Job:
    id: str
    state: str = "running"          # running | done | cancelled | error
    stage: str = "queued"           # imagery | vision | enrichment | report
    result: object | None = None    # the worker's return value (an AnalysisResult)
    error: str | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    updated_at: float = field(default_factory=time)


class JobManager:
    """Runs worker callables on daemon threads, tracking stage/state for polling."""

    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, worker: Callable[[Callable[[str], None], Callable[[], bool]], object]) -> str:
        """Spawn `worker(on_stage, should_cancel)` on a thread; return the new job id.

        The worker reports progress via on_stage(stage) and must return promptly when
        should_cancel() turns true (it may instead raise to signal cancellation)."""
        self._prune()
        job = Job(id=uuid.uuid4().hex)
        with self._lock:
            self._jobs[job.id] = job

        def run():
            try:
                result = worker(lambda stage: self._set_stage(job, stage), job.cancel_event.is_set)
                if job.cancel_event.is_set():
                    self._finish(job, state="cancelled")
                else:
                    self._finish(job, state="done", result=result)
            except Exception as exc:  # includes AnalysisCancelled
                if job.cancel_event.is_set():
                    self._finish(job, state="cancelled")
                else:
                    logger.warning("Job %s failed: %s", job.id, exc)
                    self._finish(job, state="error", error=str(exc))

        threading.Thread(target=run, daemon=True).start()
        return job.id

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        """Request cancellation. Returns False if the job is unknown."""
        job = self.get(job_id)
        if job is None:
            return False
        job.cancel_event.set()
        return True

    # --- internals --------------------------------------------------------------

    def _set_stage(self, job: Job, stage: str):
        with self._lock:
            job.stage = stage
            job.updated_at = time()

    def _finish(self, job: Job, state: str, result=None, error=None):
        with self._lock:
            job.state = state
            job.result = result
            job.error = error
            job.updated_at = time()

    def _prune(self):
        cutoff = time() - _RETAIN_SECONDS
        with self._lock:
            stale = [jid for jid, j in self._jobs.items()
                     if j.state != "running" and j.updated_at < cutoff]
            for jid in stale:
                del self._jobs[jid]
