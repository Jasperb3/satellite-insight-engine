"""Forward (place name -> coords) and reverse (coords -> place) geocoding via Nominatim."""

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderServiceError

from satviz import config
from satviz.models import Location

_geolocator = Nominatim(user_agent=config.NOMINATIM_AGENT, timeout=10)


def geocode_place(place_name: str) -> Location | None:
    """Resolve a place name to a Location, or None if it can't be found."""
    try:
        result = _geolocator.geocode(place_name)
    except GeocoderServiceError as exc:
        print(f"Geocoding service error: {exc}")
        return None
    if not result:
        return None
    return Location(
        latitude=result.latitude,
        longitude=result.longitude,
        display_name=result.address,
        raw=getattr(result, "raw", {}) or {},
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
