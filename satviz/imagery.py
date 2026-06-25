"""Google Earth Engine integration. A single private helper holds the compositing,
visualization, and export logic; the place- and coordinate-entry paths are thin wrappers."""

import logging

import ee
import requests

from satviz import config
from satviz.geocode import geocode_place, reverse_geocode
from satviz.models import ImageResult, Location

logger = logging.getLogger(__name__)

_initialized = False

# Sentinel-2 surface reflectance (10 m/px) — both confirms coverage and provides the RGB
# composite, ~3x sharper than the previous Landsat 8 (30 m/px) source.
_S2_SR = "COPERNICUS/S2_SR_HARMONIZED"

# True-colour visualisation for Sentinel-2 reflectance (values ~0-10000).
_VIZ_PARAMS = {
    "min": 0,
    "max": 3000,
    "gamma": 1.3,
    "bands": ["B4", "B3", "B2"],
}
_FORMAT_PARAMS = {
    "format": "jpg",
    "formatOptions": {"quality": 100, "subsampling": "4:4:4"},
}
# Sentinel-2 native resolution, used to size the export. Floor keeps the sidebar image and
# the vision model fed with enough pixels; ceiling avoids huge downloads / blur from upscale.
_NATIVE_M_PER_PX = 10
_MIN_DIM = 512
_MAX_DIM = 1536


def _ensure_initialized() -> None:
    global _initialized
    if _initialized:
        return
    logger.info("Initialising Earth Engine (project %s)", config.GEE_PROJECT)
    ee.Initialize(project=config.require_gee_project())
    _initialized = True


def _collection_for(point: "ee.Geometry") -> "ee.ImageCollection":
    return (
        ee.ImageCollection(_S2_SR)
        .filterBounds(point)
        .filterDate("2023-01-01", "2024-11-15")
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
    )


def _export_dimension(buffer: int) -> int:
    """Pixels across the exported square, ~native 10 m/px, bounded to avoid huge downloads
    or upscaling blur."""
    return max(_MIN_DIM, min(_MAX_DIM, round((2 * buffer) / _NATIVE_M_PER_PX)))


def _composite_and_export(latitude: float, longitude: float, buffer: int, image_path: str) -> dict:
    """Build the Sentinel-2 RGB composite, download the JPG to image_path, and return its
    Earth Engine metadata. Raises on failure so callers can surface a clear error."""
    _ensure_initialized()

    point = ee.Geometry.Point([longitude, latitude])
    region = point.buffer(buffer).bounds()

    collection = _collection_for(point)
    if collection.size().getInfo() == 0:
        raise RuntimeError("No suitable cloud-free imagery found for this location.")

    composite = collection.select(["B4", "B3", "B2"]).median()
    dimensions = _export_dimension(buffer)
    logger.info("Exporting Sentinel-2 composite at %dpx (buffer %d m)", dimensions, buffer)

    url = composite.getThumbURL(
        {**_FORMAT_PARAMS, **_VIZ_PARAMS, "region": region, "dimensions": dimensions}
    )
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    with open(image_path, "wb") as handle:
        handle.write(response.content)
    logger.info("Downloaded %d KB to %s", len(response.content) // 1024, image_path)

    return composite.getInfo()


def fetch_by_place(place_name: str, buffer: int, path_for) -> ImageResult | None:
    """Resolve a place name and fetch its image. `path_for(lat, lon, buffer)` supplies
    the output path (injected so imagery doesn't own the on-disk layout)."""
    location = geocode_place(place_name)
    if location is None:
        logger.warning("Location '%s' not found", place_name)
        return None
    return _fetch(location.latitude, location.longitude, buffer, path_for, location)


def fetch_by_coordinates(latitude: float, longitude: float, buffer: int, path_for) -> ImageResult | None:
    """Fetch the image for explicit coordinates (used by navigation)."""
    return _fetch(latitude, longitude, buffer, path_for, None)


def _fetch(latitude, longitude, buffer, path_for, location: Location | None) -> ImageResult | None:
    image_path = path_for(latitude, longitude, buffer)
    try:
        image_metadata = _composite_and_export(latitude, longitude, buffer, image_path)
    except Exception as exc:
        logger.error("Error generating image: %s", exc)
        return None

    if location is None:
        location = reverse_geocode(latitude, longitude)

    return ImageResult(
        image_path=image_path,
        location=location,
        buffer=buffer,
        image_metadata=image_metadata,
    )
