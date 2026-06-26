"""Map an engine Report (as a dict) into the browser-facing shapes: the map's run-data
payload (viewport, markers, image url) and the context the report template renders."""

import re
from datetime import date, datetime
from urllib.parse import urlsplit

_STALE_DAYS = 90


def domain(url: str) -> str:
    """Bare host of a URL for display as a source label, e.g.
    'https://www.ap.org/world/x' -> 'ap.org'. Empty for missing/garbage input."""
    if not url:
        return ""
    host = urlsplit(url if "//" in url else "//" + url).netloc
    host = host.split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def split_sentences(text: str, n: int = 3) -> tuple[str, str]:
    """Split prose into a head of the first `n` sentences and the remaining tail, so a
    long extract can be shown with a 'Read more' expander (Q3/E2)."""
    text = (text or "").strip()
    if not text:
        return "", ""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(sentences[:n]).strip(), " ".join(sentences[n:]).strip()


def _ascii_ratio(s: str) -> float:
    """Share of characters that are plain ASCII letters — a rough 'how English' score."""
    return sum(c.isascii() and c.isalpha() for c in s) / len(s) if s else 0.0


# Second-level labels that precede a country TLD (e.g. bbc.co.uk), so the registrable
# domain keeps three parts there rather than collapsing to "co.uk".
_SECOND_LEVEL = {"co", "com", "org", "gov", "ac", "net", "edu"}


def _registrable(host: str) -> str:
    """Registrable domain of a host, ignoring country subdomains so 'ca.trip.com' and
    'trip.com' dedupe together (B2)."""
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in _SECOND_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def clean_links(items: list[dict], limit: int = 5) -> list[dict]:
    """Tidy 'Further Reading' links: drop entries whose title is just a raw URL, pick the
    most English-looking segment of a piped title, dedupe by domain, and cap the count
    (Q8/E13)."""
    out, seen = [], set()
    for item in items or []:
        url = item.get("url", "")
        title = (item.get("title") or "").strip()
        if not title or title.lower().startswith(("http://", "https://")):
            continue
        if "|" in title:
            title = max((s.strip() for s in title.split("|")), key=_ascii_ratio)
        host = _registrable(domain(url))
        if host and host in seen:
            continue
        seen.add(host)
        out.append({"title": title, "url": url})
        if len(out) >= limit:
            break
    return out


# Phrases in a vision summary that suggest cloud/canopy/haze limiting ground detail.
# Worded to avoid matching the negatives ("cloud-free", "no clouds").
_OBSCURED_RE = re.compile(
    r"cloud cover|cloud-covered|cloudy|overcast|dense canopy|thick canopy|tree canopy|"
    r"limited visibility|obscured|partially hidden|heavy haze|hazy|dense smoke|under cloud|fog\b",
    re.IGNORECASE,
)


def looks_obscured(summary: str) -> bool:
    """True if the vision summary reads as cloud/canopy/haze-limited imagery (E14)."""
    return bool(_OBSCURED_RE.search(summary or ""))


# Common land-cover phrasings from the vision model -> clean tag labels (E15).
_CHIP_OVERRIDES = {
    "sparsely vegetated terrain": "Sparse Vegetation",
    "sparsely vegetated": "Sparse Vegetation",
    "forested areas": "Forest",
    "forested area": "Forest",
    "forested": "Forest",
    "built-up area": "Urban",
    "built-up areas": "Urban",
    "water body": "Water",
    "agricultural land": "Agriculture",
    "bare soil": "Bare Soil",
}
_CHIP_FILLER = {"areas", "area", "terrain", "land", "cover"}


def confidence_level(confidence: float) -> dict:
    """Map a 0–1 confidence score to a qualitative, colour-coded level. The model only
    emits round numbers, so a band label conveys the real precision better than a % (B5)."""
    if confidence >= 0.8:
        return {"label": "High", "cls": "hi"}
    if confidence >= 0.5:
        return {"label": "Medium", "cls": "mid"}
    return {"label": "Low", "cls": "lo"}


def chip_label(text: str) -> str:
    """Tidy a land-cover tag into a short Title-Case chip (E15)."""
    if not text:
        return ""
    key = text.strip().lower()
    if key in _CHIP_OVERRIDES:
        return _CHIP_OVERRIDES[key]
    words = [w for w in re.split(r"\s+", key) if w not in _CHIP_FILLER]
    return " ".join(words).title() or text.strip().title()


# Address fragments that are pure numbers/punctuation (house numbers, postcodes).
_NUMERIC_PART = re.compile(r"^[\d\s\-/]+$")


def pretty_place(display_name: str) -> str:
    """Shorten a raw geocoder display name to a readable title: drop house-number and
    postcode fragments, and for long addresses keep the most-specific part plus the
    region/country tail (e.g. '…Forum, 1, Marunouchi 3, Chiyoda, Tokyo, 100-0005, Japan'
    -> '…Forum, Tokyo, Japan'). The full name is kept for a tooltip elsewhere."""
    if not display_name:
        return ""
    parts = [p.strip() for p in display_name.split(",") if p.strip()]
    meaningful = [p for p in parts if not _NUMERIC_PART.match(p)]
    if len(meaningful) <= 3:
        return ", ".join(meaningful) or display_name.strip()
    return ", ".join([meaningful[0], *meaningful[-2:]])


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


def pretty_time(run_id: str) -> str:
    """Friendly date/time for a run_id like '2026-06-25_212427' -> 'Jun 25, 2026 · 21:24'."""
    try:
        day, _, tod = run_id.partition("_")
        dt = datetime.strptime(f"{day} {tod[:6]}", "%Y-%m-%d %H%M%S")
    except (ValueError, IndexError):
        return run_id
    return dt.strftime("%b %-d, %Y · %H:%M")


# Imagery-tier labels for history filter chips (E15).
_TIER_LABELS = {"none": "No imagery", "regional": "Regional"}


def tier_label(tier: str) -> str:
    """Human label for an imagery tier (e.g. 'none' -> 'No imagery')."""
    return _TIER_LABELS.get(tier, tier)


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
            "display_name": loc.get("display_name"),
        },
        "markers": markers_from_report(report),
    }
