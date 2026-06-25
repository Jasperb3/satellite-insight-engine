"""Tiered, always-return satellite imagery.

For any viewport the engine asks for the best image it can honestly provide and records the
provenance (which tier/source, what resolution). Sources are tried in order; if all fail the
caller still gets an ImageResult with image_path=None so the report can be produced without
imagery. Tiers:

  detailed  (<= ~12 km across): Sentinel-2 (10 m) -> Landsat 8 (30 m) -> NASA GIBS (~250 m)
  regional  (>  ~12 km across): NASA GIBS MODIS true-colour (~250 m)
"""

import logging
import math
from datetime import datetime, timedelta, timezone

import ee
import requests

from satviz import config
from satviz.geocode import geocode_place, reverse_geocode
from satviz.models import ImageResult, Location

logger = logging.getLogger(__name__)

_initialized = False

# Above this half-span (metres) we stop pretending to do fine local interpretation and
# switch to a coarse regional source + regional analysis mode.
DETAIL_CEILING_BUFFER = 6000  # 12 km across

_S2_SR = "COPERNICUS/S2_SR_HARMONIZED"
_L8 = "LANDSAT/LC08/C02/T1_TOA"
_GIBS_WMS = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
_GIBS_LAYER = "MODIS_Terra_CorrectedReflectance_TrueColor"

_FORMAT_PARAMS = {"format": "jpg", "formatOptions": {"quality": 90, "subsampling": "4:4:4"}}
_S2_VIZ = {"min": 0, "max": 3000, "gamma": 1.3, "bands": ["B4", "B3", "B2"]}
_L8_VIZ = {"min": 0.0, "max": 0.3, "gamma": 1.3, "bands": ["B4", "B3", "B2"]}

_NATIVE_M_PER_PX = 10
_MIN_DIM = 512
_MAX_DIM = 1280


def _ensure_initialized() -> None:
    global _initialized
    if _initialized:
        return
    logger.info("Initialising Earth Engine (project %s)", config.GEE_PROJECT)
    ee.Initialize(project=config.require_gee_project())
    _initialized = True


def _export_dimension(buffer: int) -> int:
    return max(_MIN_DIM, min(_MAX_DIM, round((2 * buffer) / _NATIVE_M_PER_PX)))


def _download(url: str, image_path: str) -> int:
    """GET an image URL to disk, surfacing Earth Engine's real error body (hidden by
    raise_for_status) so failures are diagnosable."""
    response = requests.get(url, timeout=120)
    if response.status_code != 200:
        detail = response.text[:300].replace("\n", " ")
        raise RuntimeError(f"{response.status_code} from imagery server: {detail}")
    with open(image_path, "wb") as handle:
        handle.write(response.content)
    return len(response.content)


def _mask_s2_clouds(img: "ee.Image") -> "ee.Image":
    qa = img.select("QA60")
    cloud = qa.bitwiseAnd(1 << 10).eq(0)
    cirrus = qa.bitwiseAnd(1 << 11).eq(0)
    return img.updateMask(cloud.And(cirrus))


def _latest_date(collection: "ee.ImageCollection") -> str | None:
    try:
        millis = collection.aggregate_max("system:time_start")
        return ee.Date(millis).format("YYYY-MM-dd").getInfo()
    except Exception:
        return None


def _source_sentinel2(lat, lon, buffer, region, image_path) -> dict:
    # Sort by cloudiness and median only the few clearest scenes: keeps the cloud-masked
    # composite cheap enough to render within the request timeout.
    coll = (
        ee.ImageCollection(_S2_SR)
        .filterBounds(region)
        .filterDate("2023-01-01", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 40))
        .sort("CLOUDY_PIXEL_PERCENTAGE")
        .limit(12)
    )
    if coll.size().getInfo() == 0:
        raise RuntimeError("no Sentinel-2 coverage")
    composite = coll.map(_mask_s2_clouds).select(["B4", "B3", "B2"]).median()
    dims = _export_dimension(buffer)
    logger.info("Trying Sentinel-2 at %dpx (buffer %d m)", dims, buffer)
    url = composite.getThumbURL({**_FORMAT_PARAMS, **_S2_VIZ, "region": region, "dimensions": dims})
    size = _download(url, image_path)
    logger.info("Sentinel-2 ok: %d KB", size // 1024)
    return {"source": "Sentinel-2", "resolution_m": 10, "date": _latest_date(coll),
            "metadata": {"collection": _S2_SR}}


def _source_landsat(lat, lon, buffer, region, image_path) -> dict:
    coll = (
        ee.ImageCollection(_L8)
        .filterBounds(region)
        .filterDate("2021-01-01", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        .filter(ee.Filter.lt("CLOUD_COVER", 30))
    )
    if coll.size().getInfo() == 0:
        raise RuntimeError("no Landsat coverage")
    composite = coll.select(["B4", "B3", "B2"]).median()
    dims = _export_dimension(buffer)
    logger.info("Trying Landsat 8 at %dpx (buffer %d m)", dims, buffer)
    url = composite.getThumbURL({**_FORMAT_PARAMS, **_L8_VIZ, "region": region, "dimensions": dims})
    size = _download(url, image_path)
    logger.info("Landsat 8 ok: %d KB", size // 1024)
    return {"source": "Landsat 8", "resolution_m": 30, "date": _latest_date(coll),
            "metadata": {"collection": _L8}}


def _source_gibs(lat, lon, buffer, region, image_path) -> dict:
    """NASA GIBS MODIS true-colour via WMS GetMap — global, daily, no key. Used for wide
    regional views and as a last-resort fallback."""
    d_lat = buffer / 111320.0
    d_lon = buffer / (111320.0 * max(0.1, math.cos(math.radians(lat))))
    # Use a recent day (yesterday UTC) for which the global mosaic is processed.
    day = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    params = {
        "SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": "1.1.1",
        "LAYERS": _GIBS_LAYER, "SRS": "EPSG:4326",
        "BBOX": f"{lon - d_lon},{lat - d_lat},{lon + d_lon},{lat + d_lat}",
        "WIDTH": 1024, "HEIGHT": 1024, "FORMAT": "image/jpeg", "TIME": day,
    }
    logger.info("Trying NASA GIBS MODIS (%s)", day)
    req = requests.Request("GET", _GIBS_WMS, params=params).prepare()
    size = _download(req.url, image_path)
    logger.info("NASA GIBS ok: %d KB", size // 1024)
    return {"source": "NASA MODIS", "resolution_m": 250, "date": day,
            "metadata": {"layer": _GIBS_LAYER, "wms": True}}


def _tier_sources(buffer: int):
    """(tier, [source_fn, ...]) for a capture half-span, tried in order."""
    if buffer <= DETAIL_CEILING_BUFFER:
        return "detailed", [_source_sentinel2, _source_landsat, _source_gibs]
    return "regional", [_source_gibs]


def fetch_by_place(place_name: str, buffer: int, path_for) -> ImageResult:
    location = geocode_place(place_name)
    if location is None:
        logger.warning("Location '%s' not found", place_name)
        location = Location(latitude=0.0, longitude=0.0, display_name=f"'{place_name}' not found")
        return ImageResult(location=location, buffer=buffer, note="Place not found.")
    return _fetch(location.latitude, location.longitude, buffer, path_for, location)


def fetch_by_coordinates(latitude: float, longitude: float, buffer: int, path_for) -> ImageResult:
    return _fetch(latitude, longitude, buffer, path_for, None)


def _fetch(latitude, longitude, buffer, path_for, location: Location | None) -> ImageResult:
    """Always returns an ImageResult. Tries each source for the tier; on total failure the
    result has image_path=None and a note, and the engine still produces a report."""
    if location is None:
        location = reverse_geocode(latitude, longitude)

    tier, sources = _tier_sources(buffer)
    image_path = path_for(latitude, longitude, buffer)

    try:
        _ensure_initialized()
        point = ee.Geometry.Point([longitude, latitude])
        region = point.buffer(buffer).bounds()
    except Exception as exc:
        logger.error("Earth Engine init failed: %s", exc)
        region = None

    for source_fn in sources:
        if region is None and source_fn is not _source_gibs:
            continue  # EE-based sources need a region
        try:
            info = source_fn(latitude, longitude, buffer, region, image_path)
            return ImageResult(
                location=location, buffer=buffer, image_path=image_path,
                imagery_tier=tier, imagery_source=info["source"],
                resolution_m=info["resolution_m"], imagery_date=info.get("date"),
                image_metadata=info["metadata"],
            )
        except Exception as exc:
            logger.warning("Imagery source %s failed: %s", getattr(source_fn, "__name__", "?"), exc)

    logger.warning("No imagery available for %.4f, %.4f @ %d m", latitude, longitude, buffer)
    return ImageResult(
        location=location, buffer=buffer, image_path=None, imagery_tier="none",
        note="No satellite imagery could be retrieved for this view.",
    )
