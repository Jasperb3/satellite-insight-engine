"""Google Earth Engine integration. A single private helper holds the compositing,
visualization, and export logic; the place- and coordinate-entry paths are thin wrappers."""

import ee
import requests

from satviz import config
from satviz.geocode import geocode_place, reverse_geocode
from satviz.models import ImageResult, Location

_initialized = False

# Sentinel-2 is used only to confirm recent cloud-free coverage exists for the point;
# the RGB composite itself comes from Landsat 8 TOA (median, low cloud) for stability.
_S2 = "COPERNICUS/S2_HARMONIZED"
_L8 = "LANDSAT/LC08/C02/T1_TOA"

_VIZ_PARAMS = {
    "min": 0.0,
    "max": 1.0,
    "gamma": 1.4,
    "bands": ["B4", "B3", "B2"],
}
_EXPORT_PARAMS = {
    "dimensions": 2048,
    "format": "jpg",
    "formatOptions": {"quality": 100, "subsampling": "4:4:4"},
}


def _ensure_initialized() -> None:
    global _initialized
    if _initialized:
        return
    ee.Initialize(project=config.require_gee_project())
    _initialized = True


def _has_coverage(point: "ee.Geometry") -> bool:
    """True if a recent, reasonably cloud-free Sentinel-2 scene exists for the point."""
    collection = (
        ee.ImageCollection(_S2)
        .filterBounds(point)
        .filterDate("2023-01-01", "2024-11-15")
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
    )
    return collection.size().getInfo() > 0


def _composite_and_export(latitude: float, longitude: float, buffer: int, image_path: str) -> dict:
    """Build the Landsat RGB composite, download the JPG to image_path, and return its
    Earth Engine metadata. Raises on failure so callers can surface a clear error."""
    _ensure_initialized()

    point = ee.Geometry.Point([longitude, latitude])
    region = point.buffer(buffer).bounds()

    if not _has_coverage(point):
        raise RuntimeError("No suitable cloud-free imagery found for this location.")

    composite = (
        ee.ImageCollection(_L8)
        .filterDate("2020-01-01", "2024-11-15")
        .filter(ee.Filter.lt("CLOUD_COVER", 10))
        .select(["B4", "B3", "B2"])
        .median()
    )

    url = composite.getThumbURL({**_EXPORT_PARAMS, **_VIZ_PARAMS, "region": region})
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    with open(image_path, "wb") as handle:
        handle.write(response.content)

    return composite.getInfo()


def fetch_by_place(place_name: str, buffer: int, path_for) -> ImageResult | None:
    """Resolve a place name and fetch its image. `path_for(lat, lon, buffer)` supplies
    the output path (injected so imagery doesn't own the on-disk layout)."""
    location = geocode_place(place_name)
    if location is None:
        print(f"Location '{place_name}' not found.")
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
        print(f"Error generating image: {exc}")
        return None

    if location is None:
        location = reverse_geocode(latitude, longitude)

    return ImageResult(
        image_path=image_path,
        location=location,
        buffer=buffer,
        image_metadata=image_metadata,
    )
