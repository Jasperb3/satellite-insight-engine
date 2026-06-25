"""Map an engine Report (as a dict) into the browser-facing shapes: the map's run-data
payload (viewport, markers, image url) and the context the report template renders."""


def image_url(run_id: str) -> str:
    return f"/asset/{run_id}/image"


def markers_from_report(report: dict) -> list[dict]:
    """POIs that carry coordinates become clickable map markers."""
    markers = []
    for poi in report.get("enrichment", {}).get("pois", []):
        lat, lon = poi.get("lat"), poi.get("lon")
        if lat is None or lon is None:
            continue
        markers.append({
            "name": poi.get("name", ""),
            "kind": poi.get("kind", ""),
            "lat": lat,
            "lon": lon,
        })
    return markers


def run_data(run_id: str, report: dict) -> dict:
    """Compact JSON the frontend reads after each panel swap to drive the map."""
    loc = report.get("location", {})
    return {
        "run_id": run_id,
        "image_url": image_url(run_id),
        "viewport": {
            "latitude": loc.get("latitude"),
            "longitude": loc.get("longitude"),
            "buffer_m": report.get("buffer"),
        },
        "markers": markers_from_report(report),
    }
