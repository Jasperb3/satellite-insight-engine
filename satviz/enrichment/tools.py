"""Individual enrichment data sources. Each function is small, has a clear docstring
(so it can double as an Ollama tool schema), and raises on failure so the orchestrator
can record a per-source error without aborting the whole run."""

import re

import requests

from satviz import config

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
        return _hosted_search(query)
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


_POI_TAGS = ["aeroway", "harbour", "man_made", "leisure", "natural", "landuse", "amenity", "tourism"]


def nearby_pois(latitude: float, longitude: float, radius_m: int = 1500) -> list[dict]:
    """List notable named OpenStreetMap features near the coordinates via Overpass.

    Args:
        latitude (float): Latitude in decimal degrees.
        longitude (float): Longitude in decimal degrees.
        radius_m (int): Search radius in metres.

    Returns:
        list: {name, kind} for named features near the point.
    """
    selectors = "".join(
        f'node(around:{radius_m},{latitude},{longitude})["{tag}"]["name"];'
        f'way(around:{radius_m},{latitude},{longitude})["{tag}"]["name"];'
        for tag in _POI_TAGS
    )
    query = f"[out:json][timeout:25];({selectors});out center 40;"
    resp = requests.post(
        "https://overpass-api.de/api/interpreter", data={"data": query},
        headers=_HEADERS, timeout=30,
    )
    resp.raise_for_status()
    seen, out = set(), []
    for el in resp.json().get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name or name in seen:
            continue
        seen.add(name)
        kind = next((tags[t] for t in _POI_TAGS if t in tags), "")
        out.append({"name": name, "kind": kind})
    return out


def weather_and_elevation(latitude: float, longitude: float) -> dict:
    """Return current weather and terrain elevation for the coordinates (Open-Meteo).

    Args:
        latitude (float): Latitude in decimal degrees.
        longitude (float): Longitude in decimal degrees.

    Returns:
        dict: {temperature, windspeed, weathercode, elevation_m}.
    """
    weather = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={"latitude": latitude, "longitude": longitude, "current_weather": True},
        headers=_HEADERS, timeout=_TIMEOUT,
    )
    weather.raise_for_status()
    current = weather.json().get("current_weather", {})

    elev = requests.get(
        "https://api.open-meteo.com/v1/elevation",
        params={"latitude": latitude, "longitude": longitude},
        headers=_HEADERS, timeout=_TIMEOUT,
    )
    elev.raise_for_status()
    elevations = elev.json().get("elevation", [])
    return {
        "temperature": current.get("temperature"),
        "windspeed": current.get("windspeed"),
        "weathercode": current.get("weathercode"),
        "elevation_m": elevations[0] if elevations else None,
    }
