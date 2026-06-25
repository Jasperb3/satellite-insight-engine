"""AnalysisService — the only thing the web layer talks to. Wraps SatVizEngine with
caching, run addressing, and structured error handling. Contains no web-framework types."""

import json
import logging
import os
from dataclasses import dataclass
from time import perf_counter

from satviz import config
from satviz.application.cache import ResultCache, viewport_key
from satviz.engine import SatVizEngine
from satviz.geocode import geocode_place
from satviz.storage import Storage

logger = logging.getLogger(__name__)


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
    def __init__(self, cache: ResultCache | None = None):
        self._cache = cache or ResultCache()

    # --- navigation-category operation ------------------------------------------

    def geocode(self, place: str):
        """Resolve a place to coordinates for a map 'fly to' — no analysis."""
        return geocode_place((place or "").strip())

    # --- analysis-category operation --------------------------------------------

    def analyze(self, latitude: float, longitude: float, buffer_m: int) -> AnalysisResult:
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
            report = engine.analyze_coordinates(latitude, longitude, buffer_m)
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
