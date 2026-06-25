"""Data contracts shared between modules. These dataclasses are the interface the
engine, presenters, and storage agree on."""

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Location:
    latitude: float
    longitude: float
    display_name: str = "Unknown location"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImageResult:
    image_path: str
    location: Location
    buffer: int
    image_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class VisionFeature:
    name: str
    confidence: float = 0.0


@dataclass
class VisionInsight:
    """Structured + narrative reading of the satellite image from the vision model."""
    land_cover: list[str] = field(default_factory=list)
    features: list[VisionFeature] = field(default_factory=list)
    summary: str = ""
    raw_response: str = ""


@dataclass
class Enrichment:
    """Corroborating context gathered by the agent's tools. Any section may be empty
    if its source was unavailable."""
    web: list[dict[str, Any]] = field(default_factory=list)
    wikipedia: dict[str, Any] = field(default_factory=dict)
    pois: list[dict[str, Any]] = field(default_factory=list)
    weather: dict[str, Any] = field(default_factory=dict)
    elevation_m: float | None = None
    summary: str = ""
    errors: list[str] = field(default_factory=list)


@dataclass
class Report:
    """Top-level merged result. This is what the engine returns; presenters render it."""
    location: Location
    buffer: int
    image_path: str
    vision: VisionInsight
    enrichment: Enrichment
    image_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
