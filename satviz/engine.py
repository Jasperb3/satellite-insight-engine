"""SatVizEngine — the UI-agnostic orchestration seam. Presenters (CLI today, an HTML GUI
later) call analyze_* and receive a Report. The engine does no printing and opens no
windows; it only persists outputs via Storage."""

import logging
from time import perf_counter
from typing import Callable

from satviz import imagery
from satviz.enrichment import enrich
from satviz.models import ImageResult, Report, VisionInsight
from satviz.report import build_report
from satviz.storage import Storage
from satviz.vision import describe

logger = logging.getLogger(__name__)

# Coarse pipeline stages reported through the optional on_stage callback so a UI can show
# live progress. The engine stays UI-agnostic — it only invokes a plain callable.
StageCallback = Callable[[str], None]
CancelCheck = Callable[[], bool]


class AnalysisCancelled(Exception):
    """Raised when a cooperative cancel was requested between pipeline stages."""


def _noop(_stage: str) -> None:
    pass


class SatVizEngine:
    def __init__(self, storage: Storage | None = None):
        self.storage = storage or Storage()

    def analyze_place(self, place_name: str, buffer: int,
                      on_stage: StageCallback | None = None,
                      should_cancel: CancelCheck | None = None) -> Report:
        logger.info("Analyse place '%s' (buffer %d m)", place_name, buffer)
        on_stage = on_stage or _noop
        on_stage("imagery")
        image = imagery.fetch_by_place(place_name, buffer, self.storage.path_for)
        return self._analyze(image, on_stage, should_cancel)

    def analyze_coordinates(self, latitude: float, longitude: float, buffer: int,
                            on_stage: StageCallback | None = None,
                            should_cancel: CancelCheck | None = None) -> Report:
        logger.info("Analyse %.4f, %.4f (buffer %d m)", latitude, longitude, buffer)
        on_stage = on_stage or _noop
        on_stage("imagery")
        image = imagery.fetch_by_coordinates(latitude, longitude, buffer, self.storage.path_for)
        return self._analyze(image, on_stage, should_cancel)

    def _analyze(self, image: ImageResult, on_stage: StageCallback = _noop,
                 should_cancel: CancelCheck | None = None) -> Report:
        """Always returns a Report (the always-return invariant). Vision is skipped when no
        imagery could be retrieved; enrichment runs regardless."""
        started = perf_counter()

        def _check():
            if should_cancel and should_cancel():
                raise AnalysisCancelled()

        _check()
        if image.image_path:
            on_stage("vision")
            t0 = perf_counter()
            vision = describe(image)
            logger.info("Vision (%s) done in %d ms (%d features)",
                        image.imagery_tier, int((perf_counter() - t0) * 1000), len(vision.features))
        else:
            vision = VisionInsight(summary=image.note or "No satellite imagery available here.")
            logger.info("No imagery; skipping vision")

        _check()
        on_stage("enrichment")
        t0 = perf_counter()
        enrichment = enrich(image, vision)
        logger.info("Enrichment done in %d ms (%d POIs, %d web)",
                    int((perf_counter() - t0) * 1000), len(enrichment.pois), len(enrichment.web))

        on_stage("report")
        report = build_report(image, vision, enrichment)
        json_path, _ = self.storage.write_report(report)
        logger.info("Report written to %s (total %d ms)",
                    json_path, int((perf_counter() - started) * 1000))
        return report
