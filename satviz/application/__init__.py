"""Application layer: browser-facing orchestration over the UI-agnostic engine.

Web routes call AnalysisService (never SatVizEngine directly). This layer normalises
requests into engine calls, maps engine output into browser DTOs, applies caching, and
turns failures into structured, user-safe results."""

from satviz.application.service import AnalysisService, AnalysisResult

__all__ = ["AnalysisService", "AnalysisResult"]
