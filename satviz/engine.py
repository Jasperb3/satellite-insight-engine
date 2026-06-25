"""SatVizEngine — the UI-agnostic orchestration seam. Presenters (CLI today, an HTML GUI
later) call analyze_* and receive a Report. The engine does no printing and opens no
windows; it only persists outputs via Storage."""

import logging
from time import perf_counter

from satviz import imagery
from satviz.enrichment import enrich
from satviz.models import ImageResult, Report, VisionInsight
from satviz.report import build_report
from satviz.storage import Storage
from satviz.vision import describe

logger = logging.getLogger(__name__)


class SatVizEngine:
    def __init__(self, storage: Storage | None = None):
        self.storage = storage or Storage()

    def analyze_place(self, place_name: str, buffer: int) -> Report:
        logger.info("Analyse place '%s' (buffer %d m)", place_name, buffer)
        image = imagery.fetch_by_place(place_name, buffer, self.storage.path_for)
        return self._analyze(image)

    def analyze_coordinates(self, latitude: float, longitude: float, buffer: int) -> Report:
        logger.info("Analyse %.4f, %.4f (buffer %d m)", latitude, longitude, buffer)
        image = imagery.fetch_by_coordinates(latitude, longitude, buffer, self.storage.path_for)
        return self._analyze(image)

    def _analyze(self, image: ImageResult) -> Report:
        """Always returns a Report (the always-return invariant). Vision is skipped when no
        imagery could be retrieved; enrichment runs regardless."""
        started = perf_counter()

        if image.image_path:
            t0 = perf_counter()
            vision = describe(image)
            logger.info("Vision (%s) done in %d ms (%d features)",
                        image.imagery_tier, int((perf_counter() - t0) * 1000), len(vision.features))
        else:
            vision = VisionInsight(summary=image.note or "No satellite imagery available here.")
            logger.info("No imagery; skipping vision")

        t0 = perf_counter()
        enrichment = enrich(image, vision)
        logger.info("Enrichment done in %d ms (%d POIs, %d web)",
                    int((perf_counter() - t0) * 1000), len(enrichment.pois), len(enrichment.web))

        report = build_report(image, vision, enrichment)
        json_path, _ = self.storage.write_report(report)
        logger.info("Report written to %s (total %d ms)",
                    json_path, int((perf_counter() - started) * 1000))
        return report
