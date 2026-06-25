"""SatVizEngine — the UI-agnostic orchestration seam. Presenters (CLI today, an HTML GUI
later) call analyze_* and receive a Report. The engine does no printing and opens no
windows; it only persists outputs via Storage."""

import logging
from time import perf_counter

from satviz import imagery
from satviz.enrichment import enrich
from satviz.models import ImageResult, Report
from satviz.report import build_report
from satviz.storage import Storage
from satviz.vision import describe

logger = logging.getLogger(__name__)


class SatVizEngine:
    def __init__(self, storage: Storage | None = None):
        self.storage = storage or Storage()

    def analyze_place(self, place_name: str, buffer: int) -> Report | None:
        logger.info("Analyse place '%s' (buffer %d m)", place_name, buffer)
        image = imagery.fetch_by_place(place_name, buffer, self.storage.path_for)
        return self._analyze(image)

    def analyze_coordinates(self, latitude: float, longitude: float, buffer: int) -> Report | None:
        logger.info("Analyse %.4f, %.4f (buffer %d m)", latitude, longitude, buffer)
        image = imagery.fetch_by_coordinates(latitude, longitude, buffer, self.storage.path_for)
        return self._analyze(image)

    def _analyze(self, image: ImageResult | None) -> Report | None:
        if image is None:
            logger.warning("No image produced; aborting analysis")
            return None

        started = perf_counter()
        t0 = perf_counter()
        vision = describe(image)
        logger.info("Vision done in %d ms (%d features)",
                    int((perf_counter() - t0) * 1000), len(vision.features))

        t0 = perf_counter()
        enrichment = enrich(image, vision)
        logger.info("Enrichment done in %d ms (%d POIs, %d web)",
                    int((perf_counter() - t0) * 1000), len(enrichment.pois), len(enrichment.web))

        report = build_report(image, vision, enrichment)
        json_path, _ = self.storage.write_report(report)
        logger.info("Report written to %s (total %d ms)",
                    json_path, int((perf_counter() - started) * 1000))
        return report
