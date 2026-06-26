"""Individual enrichment data sources. Each function is small, has a clear docstring
(so it can double as an Ollama tool schema), and raises on failure so the orchestrator
can record a per-source error without aborting the whole run."""

import logging
import re

import requests

from satviz import config

logger = logging.getLogger(__name__)

_TIMEOUT = 20
_HEADERS = {"User-Agent": config.NOMINATIM_AGENT}


def search_web(query: str) -> list[dict]:
    """Search the web for a query and return a list of {title, url, content} results.

    Args:
        query (str): The search query.

    Returns:
        list: Up to five search results.
    """
    if config.has_hosted_search():
        try:
            return _hosted_search(query)
        except Exception as exc:
            # Rate limit (429) or any hosted failure: fall back to the free source.
            logger.warning("Hosted web search failed (%s); falling back to Wikipedia search", exc)
            return _wikipedia_search(query)
    return _wikipedia_search(query)


def _hosted_search(query: str) -> list[dict]:
    from ollama import Client

    client = Client(
        host="https://ollama.com",
        headers={"Authorization": f"Bearer {config.OLLAMA_API_KEY}"},
    )
    results = client.web_search(query=query, max_results=5)
    out = []
    for r in results.results:
        out.append({"title": r.title, "url": r.url, "content": (r.content or "")[:1000]})
    return out


def _wikipedia_search(query: str) -> list[dict]:
    """Free, no-key fallback: Wikipedia full-text search."""
    resp = requests.get(
        "https://en.wikipedia.org/w/api.php",
        params={
            "action": "query", "list": "search", "srsearch": query,
            "format": "json", "srlimit": 5,
        },
        headers=_HEADERS, timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    hits = resp.json().get("query", {}).get("search", [])
    out = []
    for h in hits:
        title = h.get("title", "")
        snippet = re.sub(r"<[^>]+>", "", h.get("snippet", ""))
        url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
        out.append({"title": title, "url": url, "content": snippet})
    return out


def wikipedia_nearby(latitude: float, longitude: float) -> dict:
    """Return a summary of the Wikipedia article nearest to the given coordinates.

    Args:
        latitude (float): Latitude in decimal degrees.
        longitude (float): Longitude in decimal degrees.

    Returns:
        dict: {title, extract, url} for the nearest article, or {} if none found.
    """
    geo = requests.get(
        "https://en.wikipedia.org/w/api.php",
        params={
            "action": "query", "list": "geosearch",
            "gscoord": f"{latitude}|{longitude}", "gsradius": 10000,
            "gslimit": 1, "format": "json",
        },
        headers=_HEADERS, timeout=_TIMEOUT,
    )
    geo.raise_for_status()
    pages = geo.json().get("query", {}).get("geosearch", [])
    if not pages:
        return {}
    title = pages[0]["title"]
    summary = requests.get(
        f"https://en.wikipedia.org/api/rest_v1/page/summary/{title.replace(' ', '_')}",
        headers=_HEADERS, timeout=_TIMEOUT,
    )
    summary.raise_for_status()
    data = summary.json()
    return {
        "title": data.get("title", title),
        "extract": data.get("extract", ""),
        "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
    }


# Overpass mirrors tried in order — the main endpoint frequently 504s under load.
_OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]


def _overpass_request(query: str) -> requests.Response:
    last_exc = None
    for endpoint in _OVERPASS_ENDPOINTS:
        try:
            resp = requests.post(endpoint, data={"data": query}, headers=_HEADERS, timeout=30)
            resp.raise_for_status()
            return resp
        except Exception as exc:
            last_exc = exc
            continue
    raise last_exc


_POI_TAGS = ["aeroway", "harbour", "man_made", "leisure", "natural", "landuse", "amenity", "tourism"]


# Signage and generic markers add noise rather than insight; rank them last.
_DEMOTED_KINDS = {"information", "guidepost", "artwork", "yes"}

# Dead businesses leak into OSM via closure phrases in the name or lifecycle-prefixed
# tags. Drop them so the POI list reflects what's actually there (B6).
_CLOSED_NAME_RE = re.compile(r"fechad|closed|encerrad|fermé|ferme|geschlossen|cerrad",
                             re.IGNORECASE)
_CLOSED_TAG_PREFIXES = ("disused:", "abandoned:", "razed:", "demolished:", "removed:")


def _is_closed(tags: dict, name: str) -> bool:
    """True if an OSM feature reads as permanently closed / no longer present."""
    if _CLOSED_NAME_RE.search(name):
        return True
    return any(k.startswith(_CLOSED_TAG_PREFIXES) for k in tags)


def _poi_rank(poi: dict) -> int:
    """Lower sorts first. Substantive features rank above tourist signage."""
    if poi["kind"] in _DEMOTED_KINDS:
        return 2
    if poi["tag"] == "tourism":
        return 1
    return 0


def nearby_pois(latitude: float, longitude: float, radius_m: int = 1500,
                limit: int = 20) -> list[dict]:
    """List notable named OpenStreetMap features near the coordinates via Overpass,
    ranked so substantive features come before tourist signage.

    Args:
        latitude (float): Latitude in decimal degrees.
        longitude (float): Longitude in decimal degrees.
        radius_m (int): Search radius in metres.
        limit (int): Maximum number of features to return.

    Returns:
        list: {name, kind, lat, lon} for named features near the point.
    """
    selectors = "".join(
        f'node(around:{radius_m},{latitude},{longitude})["{tag}"]["name"];'
        f'way(around:{radius_m},{latitude},{longitude})["{tag}"]["name"];'
        for tag in _POI_TAGS
    )
    query = f"[out:json][timeout:25];({selectors});out center 60;"
    resp = _overpass_request(query)
    seen, out = set(), []
    for el in resp.json().get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name or name in seen or _is_closed(tags, name):
            continue
        seen.add(name)
        tag = next((t for t in _POI_TAGS if t in tags), "")
        center = el.get("center", {})
        out.append({
            "name": name,
            "tag": tag,
            "kind": tags.get(tag, ""),
            "lat": el.get("lat", center.get("lat")),
            "lon": el.get("lon", center.get("lon")),
        })
    out.sort(key=_poi_rank)
    return out[:limit]


# WMO weather codes -> (label, emoji). Compact map covering the common buckets.
_WMO = {
    0: ("Clear sky", "☀️"), 1: ("Mainly clear", "🌤️"), 2: ("Partly cloudy", "⛅"),
    3: ("Overcast", "☁️"), 45: ("Fog", "🌫️"), 48: ("Rime fog", "🌫️"),
    51: ("Light drizzle", "🌦️"), 53: ("Drizzle", "🌦️"), 55: ("Heavy drizzle", "🌦️"),
    61: ("Light rain", "🌧️"), 63: ("Rain", "🌧️"), 65: ("Heavy rain", "🌧️"),
    71: ("Light snow", "🌨️"), 73: ("Snow", "🌨️"), 75: ("Heavy snow", "❄️"),
    80: ("Rain showers", "🌦️"), 81: ("Rain showers", "🌦️"), 82: ("Violent showers", "⛈️"),
    95: ("Thunderstorm", "⛈️"), 96: ("Thunderstorm + hail", "⛈️"), 99: ("Thunderstorm + hail", "⛈️"),
}


def weather_and_elevation(latitude: float, longitude: float) -> dict:
    """Return current weather and terrain elevation for the coordinates (Open-Meteo).

    Args:
        latitude (float): Latitude in decimal degrees.
        longitude (float): Longitude in decimal degrees.

    Returns:
        dict: temperature, feels_like, humidity, wind_kmh, label, icon, forecast_url, elevation_m.
    """
    weather = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": latitude, "longitude": longitude,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,"
                       "weather_code,wind_speed_10m",
        },
        headers=_HEADERS, timeout=_TIMEOUT,
    )
    weather.raise_for_status()
    current = weather.json().get("current", {})
    code = current.get("weather_code")
    label, icon = _WMO.get(code, ("", "🛰️"))

    elev = requests.get(
        "https://api.open-meteo.com/v1/elevation",
        params={"latitude": latitude, "longitude": longitude},
        headers=_HEADERS, timeout=_TIMEOUT,
    )
    elev.raise_for_status()
    elevations = elev.json().get("elevation", [])
    return {
        "temperature": current.get("temperature_2m"),
        "feels_like": current.get("apparent_temperature"),
        "humidity": current.get("relative_humidity_2m"),
        "wind_kmh": current.get("wind_speed_10m"),
        "label": label,
        "icon": icon,
        "forecast_url": f"https://www.yr.no/en/forecast/daily-table/{latitude},{longitude}",
        "elevation_m": elevations[0] if elevations else None,
    }


def recent_news(place: str) -> dict:
    """Recent news about a place via Tavily (synthesized answer + sources). Returns
    {summary, results:[{title,url}]}. Requires TAVILY_API_KEY.

    Args:
        place (str): The place/area name to search news for.
    """
    if not config.TAVILY_API_KEY:
        return {"summary": "", "results": []}
    resp = requests.post(
        "https://api.tavily.com/search",
        headers={"Authorization": f"Bearer {config.TAVILY_API_KEY}"},
        json={
            "query": f"recent news about {place}",
            "topic": "news", "time_range": "month",
            "max_results": 5, "search_depth": "basic", "include_answer": True,
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    results = [{"title": r.get("title", ""), "url": r.get("url", "")}
               for r in data.get("results", [])]
    return {"summary": (data.get("answer") or "").strip(), "results": results}


def area_history(title: str) -> str:
    """A fuller historical/background extract for a Wikipedia article title (plain text).

    Args:
        title (str): The Wikipedia article title (e.g. from wikipedia_nearby).
    """
    if not title:
        return ""
    resp = requests.get(
        "https://en.wikipedia.org/w/api.php",
        params={
            "action": "query", "prop": "extracts", "exsentences": 6,
            "explaintext": 1, "redirects": 1, "format": "json", "titles": title,
        },
        headers=_HEADERS, timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages", {})
    for page in pages.values():
        if page.get("extract"):
            # Plain-text extracts can still carry MediaWiki "== Section ==" headers; drop them.
            text = re.sub(r"\s*={2,}[^=\n]+={2,}\s*", " ", page["extract"])
            return text.strip()
    return ""


def natural_events(latitude: float, longitude: float, radius_deg: float = 5.0) -> list[dict]:
    """Active natural events (wildfires, storms, floods, volcanoes) near the point via NASA
    EONET (no key). Returns [{title, category, date, url}].

    Args:
        latitude (float): Latitude in decimal degrees.
        longitude (float): Longitude in decimal degrees.
        radius_deg (float): Half-size of the bounding box in degrees.
    """
    bbox = f"{longitude - radius_deg},{latitude + radius_deg}," \
           f"{longitude + radius_deg},{latitude - radius_deg}"
    resp = requests.get(
        "https://eonet.gsfc.nasa.gov/api/v3/events",
        params={"status": "open", "bbox": bbox, "limit": 10},
        headers=_HEADERS, timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    out = []
    for ev in resp.json().get("events", []):
        cats = ev.get("categories", [])
        geom = ev.get("geometry", [])
        out.append({
            "title": ev.get("title", ""),
            "category": cats[0]["title"] if cats else "",
            "date": geom[-1]["date"][:10] if geom and geom[-1].get("date") else "",
            "url": ev.get("link", ""),
        })
    return out
