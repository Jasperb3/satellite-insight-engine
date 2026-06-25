"""Enrichment layer: gathers corroborating context about a location from open
geographic APIs and the web, driven in part by the lfm2.5 tool-using agent."""

from satviz.enrichment.orchestrator import enrich

__all__ = ["enrich"]
