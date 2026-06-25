"""AnalysisService — the only thing the web layer talks to. Wraps SatVizEngine with
caching, run addressing, and structured error handling. Contains no web-framework types."""

import json
import logging
import os
from dataclasses import dataclass
from time import perf_counter

from satviz import config
from satviz.application.cache import ResultCache, viewport_key
from satviz.application.jobs import JobManager
from satviz.engine import AnalysisCancelled, SatVizEngine
from satviz.geocode import geocode_place, reverse_geocode
from satviz.storage import Storage

logger = logging.getLogger(__name__)


def _is_populated(display_name: str) -> bool:
    """False for the geocoder's open-water / not-found fallbacks."""
    return bool(display_name) and display_name != "Open water or remote area" \
        and "not found" not in display_name.lower()


@dataclass
class AnalysisResult:
    ok: bool
    run_id: str | None = None
    report: dict | None = None          # engine Report as a dict (the panel renders this)
    viewport: dict | None = None        # {latitude, longitude, buffer_m}
    timing_ms: int | None = None
    error: str | None = None
    failure_kind: str | None = None     # not_found | analysis_failed | unavailable


class AnalysisService:
    def __init__(self, cache: ResultCache | None = None, jobs: JobManager | None = None):
        self._cache = cache or ResultCache()
        self._jobs = jobs or JobManager()

    # --- navigation-category operation ------------------------------------------

    def geocode(self, place: str):
        """Resolve a place to coordinates for a map 'fly to' — no analysis."""
        return geocode_place((place or "").strip())

    def reverse(self, latitude: float, longitude: float) -> dict:
        """Quick reverse-geocode so the UI can warn before a long open-water capture (E12)."""
        location = reverse_geocode(latitude, longitude)
        return {"display_name": location.display_name,
                "located": _is_populated(location.display_name)}

    # --- analysis-category operation --------------------------------------------

    def analyze(self, latitude: float, longitude: float, buffer_m: int,
                on_stage=None, should_cancel=None) -> AnalysisResult:
        key = viewport_key(latitude, longitude, buffer_m)
        cached = self._cache.get(key)
        if cached is not None:
            logger.info("Cache hit for %.4f, %.4f @ %d m", latitude, longitude, buffer_m)
            return cached

        logger.info("Snapshot request %.4f, %.4f @ %d m", latitude, longitude, buffer_m)
        started = perf_counter()
        try:
            storage = Storage()
            engine = SatVizEngine(storage)
            report = engine.analyze_coordinates(latitude, longitude, buffer_m,
                                                on_stage=on_stage, should_cancel=should_cancel)
        except AnalysisCancelled:
            raise
        except Exception as exc:
            return AnalysisResult(ok=False, error=f"Backend unavailable: {exc}",
                                  failure_kind="unavailable",
                                  viewport={"latitude": latitude, "longitude": longitude,
                                            "buffer_m": buffer_m})
        if report is None:
            return AnalysisResult(ok=False,
                                  error="No cloud-free imagery available for this location.",
                                  failure_kind="analysis_failed",
                                  viewport={"latitude": latitude, "longitude": longitude,
                                            "buffer_m": buffer_m})

        report_dict = report.to_dict()
        result = AnalysisResult(
            ok=True,
            run_id=storage.run_id,
            report=report_dict,
            viewport={
                "latitude": report.location.latitude,
                "longitude": report.location.longitude,
                "buffer_m": report.buffer,
            },
            timing_ms=int((perf_counter() - started) * 1000),
        )
        self._cache.put(key, result)
        return result

    # --- async job flow (live progress + cancel) --------------------------------

    def start_analysis(self, latitude: float, longitude: float, buffer_m: int) -> str:
        """Kick off an analysis on a background thread; return a job id to poll."""
        return self._jobs.start(
            lambda on_stage, should_cancel:
                self.analyze(latitude, longitude, buffer_m, on_stage, should_cancel)
        )

    def job_status(self, job_id: str) -> dict | None:
        """Poll-friendly snapshot of a job, or None if the id is unknown."""
        job = self._jobs.get(job_id)
        if job is None:
            return None
        status = {"state": job.state, "stage": job.stage}
        if job.state == "done" and job.result is not None:
            status["ok"] = job.result.ok
            status["run_id"] = job.result.run_id
        elif job.state == "error":
            status["error"] = job.error
        return status

    def job_result(self, job_id: str) -> AnalysisResult | None:
        """The finished AnalysisResult for rendering the report partial, or None."""
        job = self._jobs.get(job_id)
        if job is None or not isinstance(job.result, AnalysisResult):
            return None
        return job.result

    def cancel_analysis(self, job_id: str) -> bool:
        return self._jobs.cancel(job_id)

    # --- saved-run access -------------------------------------------------------

    def get_run(self, run_id: str) -> AnalysisResult:
        run_dir = Storage.resolve_run_dir(run_id)
        json_path = Storage.find_report_json(run_dir)
        if not json_path:
            return AnalysisResult(ok=False, error="Run not found.", failure_kind="not_found")
        with open(json_path) as handle:
            report_dict = json.load(handle)
        loc = report_dict.get("location", {})
        return AnalysisResult(
            ok=True, run_id=run_id, report=report_dict,
            viewport={"latitude": loc.get("latitude"), "longitude": loc.get("longitude"),
                      "buffer_m": report_dict.get("buffer")},
        )

    def image_path_for(self, run_id: str) -> str | None:
        return Storage.find_image(Storage.resolve_run_dir(run_id))

    def list_runs(self, limit: int = 25) -> list[dict]:
        """Recent saved runs (newest first) for the history list."""
        root = config.OUTPUT_ROOT
        if not os.path.isdir(root):
            return []
        runs = []
        for day in sorted(os.listdir(root), reverse=True):
            day_dir = os.path.join(root, day)
            if not os.path.isdir(day_dir):
                continue
            for folder in sorted(os.listdir(day_dir), reverse=True):
                run_dir = os.path.join(day_dir, folder)
                json_path = Storage.find_report_json(run_dir)
                if not json_path:
                    continue
                run_id = f"{day}_{folder}"
                try:
                    with open(json_path) as handle:
                        data = json.load(handle)
                    name = data.get("location", {}).get("display_name", run_id)
                except Exception:
                    name = run_id
                runs.append({"run_id": run_id, "display_name": name,
                             "image_url": f"/asset/{run_id}/image"})
                if len(runs) >= limit:
                    return runs
        return runs
