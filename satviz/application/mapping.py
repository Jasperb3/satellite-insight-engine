"""Map an engine Report (as a dict) into the browser-facing shapes: the map's run-data
payload (viewport, markers, image url) and the context the report template renders."""

from datetime import date, datetime

_STALE_DAYS = 90


def _days_old(date_str: str):
    """Whole days between an ISO date (YYYY-MM-DD) and today, or None if unparseable."""
    if not date_str:
        return None
    try:
        captured = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return (date.today() - captured).days


def relative_age(date_str: str) -> str:
    """Human relative age of an imagery date, e.g. 'today', 'yesterday', '29 days ago'."""
    days = _days_old(date_str)
    if days is None:
        return ""
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 60:
        return f"{days} days ago"
    months = days // 30
    return f"{months} months ago"


def is_stale(date_str: str, days: int = _STALE_DAYS) -> bool:
    """True if the imagery is older than the stale threshold."""
    age = _days_old(date_str)
    return age is not None and age > days


def image_url(run_id: str) -> str:
    return f"/asset/{run_id}/image"


# OSM tag values that don't title-case cleanly. Everything else falls back to
# turning "post_office" -> "Post Office".
_KIND_OVERRIDES = {
    "atm": "ATM",
    "bbq": "BBQ",
    "pub": "Pub",
    "parking_entrance": "Car Park Entrance",
}


def pretty_kind(kind: str) -> str:
    """Human-readable label for a raw OSM tag value (e.g. 'fast_food' -> 'Fast Food')."""
    if not kind:
        return ""
    return _KIND_OVERRIDES.get(kind, kind.replace("_", " ").title())


# Raw OSM kind -> map-marker emoji (E14). Checked before the per-tag fallback.
_KIND_ICONS = {
    "restaurant": "🍽️", "cafe": "☕", "fast_food": "🍔", "pub": "🍺", "bar": "🍸",
    "fuel": "⛽", "bank": "🏦", "atm": "🏦",
    "hotel": "🏨", "hostel": "🏨", "guest_house": "🏨", "motel": "🏨",
    "hospital": "🏥", "pharmacy": "💊", "clinic": "🏥",
    "school": "🎓", "university": "🎓", "college": "🎓", "library": "📚",
    "place_of_worship": "⛪",
    "museum": "🏛️", "attraction": "📸", "artwork": "🎨", "viewpoint": "👁️", "memorial": "🗿",
    "parking": "🅿️", "parking_entrance": "🅿️", "bus_station": "🚌", "station": "🚉",
    "ferry_terminal": "⛴️", "aerodrome": "✈️",
    "peak": "⛰️", "beach": "🏖️", "park": "🌳", "water": "💧", "wood": "🌲",
}

# Per-tag fallback when the specific kind isn't mapped above.
_TAG_ICONS = {
    "aeroway": "✈️", "harbour": "⚓", "natural": "🌳", "leisure": "🌳",
    "tourism": "📸", "amenity": "📍", "man_made": "🏗️", "landuse": "🗺️",
}


def marker_icon(tag: str, kind: str) -> str:
    """Pick an emoji for a POI marker from its OSM kind, falling back to its tag (E14)."""
    return _KIND_ICONS.get(kind) or _TAG_ICONS.get(tag) or "📍"


def markers_from_report(report: dict) -> list[dict]:
    """POIs that carry coordinates become clickable map markers."""
    markers = []
    for poi in report.get("enrichment", {}).get("pois", []):
        lat, lon = poi.get("lat"), poi.get("lon")
        if lat is None or lon is None:
            continue
        markers.append({
            "name": poi.get("name", ""),
            "kind": pretty_kind(poi.get("kind", "")),
            "icon": marker_icon(poi.get("tag", ""), poi.get("kind", "")),
            "lat": lat,
            "lon": lon,
        })
    return markers


def run_data(run_id: str, report: dict) -> dict:
    """Compact JSON the frontend reads after each panel swap to drive the map."""
    loc = report.get("location", {})
    return {
        "run_id": run_id,
        "image_url": image_url(run_id) if report.get("image_path") else None,
        "viewport": {
            "latitude": loc.get("latitude"),
            "longitude": loc.get("longitude"),
            "buffer_m": report.get("buffer"),
        },
        "markers": markers_from_report(report),
    }
