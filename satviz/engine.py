"""SatVizEngine — the UI-agnostic orchestration seam. Presenters (CLI today, an HTML GUI
later) call analyze_* and receive a Report. The engine does no printing and opens no
windows; it only persists outputs via Storage."""

from satviz import imagery
from satviz.enrichment import enrich
from satviz.models import ImageResult, Report
from satviz.report import build_report
from satviz.storage import Storage
from satviz.vision import describe


class SatVizEngine:
    def __init__(self, storage: Storage | None = None):
        self.storage = storage or Storage()

    def analyze_place(self, place_name: str, buffer: int) -> Report | None:
        image = imagery.fetch_by_place(place_name, buffer, self.storage.path_for)
        return self._analyze(image)

    def analyze_coordinates(self, latitude: float, longitude: float, buffer: int) -> Report | None:
        image = imagery.fetch_by_coordinates(latitude, longitude, buffer, self.storage.path_for)
        return self._analyze(image)

    def _analyze(self, image: ImageResult | None) -> Report | None:
        if image is None:
            return None
        vision = describe(image)
        enrichment = enrich(image, vision)
        report = build_report(image, vision, enrichment)
        self.storage.write_report(report)
        return report
