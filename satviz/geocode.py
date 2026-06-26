"""Forward (place name -> coords) and reverse (coords -> place) geocoding via Nominatim."""

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderServiceError

from satviz import config
from satviz.models import Location

_geolocator = Nominatim(user_agent=config.NOMINATIM_AGENT, timeout=10)

# OSM classes for a business/POI node: when a typed landmark resolves to one of these, the
# node's name (a café/gallery inside the landmark) makes a worse title than the search term.
_AMENITY_CLASSES = {"amenity", "shop", "office", "craft"}


def geocode_place(place_name: str) -> Location | None:
    """Resolve a place name to a Location, or None if it can't be found."""
    try:
        result = _geolocator.geocode(place_name)
    except GeocoderServiceError as exc:
        print(f"Geocoding service error: {exc}")
        return None
    if not result:
        return None
    raw = getattr(result, "raw", {}) or {}
    display = result.address
    # If the geocoder landed on a business inside the place the user typed, prefer the search
    # term as the title, keeping the region/country tail for context (B1/E1).
    if raw.get("class") in _AMENITY_CLASSES:
        tail = ", ".join(p.strip() for p in display.split(",")[-2:] if p.strip())
        display = f"{place_name.strip()}, {tail}" if tail else place_name.strip()
    return Location(
        latitude=result.latitude,
        longitude=result.longitude,
        display_name=display,
        raw=raw,
    )


def _approximate_if_generic(display: str) -> str:
    """Country/region-only reverse results (e.g. "Australia" for a point in the Great Barrier
    Reef) carry no comma-separated detail. Mark them approximate so the title doesn't imply
    a precise address (B7)."""
    if "," in display:
        return display
    return f"{display} (approx.)"


def reverse_geocode(latitude: float, longitude: float) -> Location:
    """Build a Location for coordinates, filling display_name via reverse geocoding."""
    try:
        result = _geolocator.reverse(f"{latitude}, {longitude}", language="en")
        raw = result.raw if result else {}
        # Nominatim returns nothing over open water / remote areas — label honestly rather
        # than "not found" so downstream grounding treats it as a real, sparse location.
        display = raw.get("display_name")
        display = _approximate_if_generic(display) if display else "Open water or remote area"
    except Exception as exc:  # network/service errors shouldn't kill the run
        raw = {"error": str(exc)}
        display = "Open water or remote area"
    return Location(latitude=latitude, longitude=longitude, display_name=display, raw=raw)
