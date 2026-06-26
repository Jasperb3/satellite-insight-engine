from satviz.enrichment import orchestrator, tools
from satviz.models import Enrichment


def test_search_web_uses_hosted_when_key_present(monkeypatch):
    monkeypatch.setattr(tools.config, "OLLAMA_API_KEY", "k")
    monkeypatch.setattr(tools.config, "has_hosted_search", lambda: True)
    called = {}
    monkeypatch.setattr(tools, "_hosted_search", lambda q: called.setdefault("hosted", q) or [])
    monkeypatch.setattr(tools, "_wikipedia_search", lambda q: called.setdefault("free", q) or [])

    tools.search_web("eiffel tower")
    assert "hosted" in called and "free" not in called


def test_search_web_falls_back_when_no_key(monkeypatch):
    monkeypatch.setattr(tools.config, "has_hosted_search", lambda: False)
    called = {}
    monkeypatch.setattr(tools, "_hosted_search", lambda q: called.setdefault("hosted", q) or [])
    monkeypatch.setattr(tools, "_wikipedia_search", lambda q: called.setdefault("free", q) or [])

    tools.search_web("eiffel tower")
    assert "free" in called and "hosted" not in called


def test_search_web_falls_back_when_hosted_rate_limited(monkeypatch):
    monkeypatch.setattr(tools.config, "has_hosted_search", lambda: True)
    called = {}

    def boom(q):
        called["hosted"] = q
        raise RuntimeError("429 rate limit")

    def free(q):
        called["free"] = q
        return [{"title": "x", "url": "u", "content": "c"}]

    monkeypatch.setattr(tools, "_hosted_search", boom)
    monkeypatch.setattr(tools, "_wikipedia_search", free)

    result = tools.search_web("giza")
    assert called.get("hosted") == "giza" and called.get("free") == "giza"
    assert result == [{"title": "x", "url": "u", "content": "c"}]


def test_safe_records_error_and_continues():
    enrichment = Enrichment()

    def boom():
        raise RuntimeError("down")

    result = orchestrator._safe(enrichment, "pois", boom)
    assert result is None
    assert enrichment.errors == ["pois: down"]


def test_safe_returns_value_on_success():
    enrichment = Enrichment()
    assert orchestrator._safe(enrichment, "wikipedia", lambda: {"ok": 1}) == {"ok": 1}
    assert enrichment.errors == []


def test_safe_error_strips_request_url_and_coords():
    enrichment = Enrichment()

    def boom():
        raise RuntimeError(
            "503 Server Error: Service Unavailable for url: "
            "https://eonet.gsfc.nasa.gov/api/v3/events?bbox=1,2,3,4"
        )

    orchestrator._safe(enrichment, "events", boom)
    recorded = enrichment.errors[0]
    assert "http" not in recorded and "bbox" not in recorded
    assert recorded == "events: 503 Server Error: Service Unavailable"


def test_area_history_strips_section_headers(monkeypatch):
    payload = {"query": {"pages": {"1": {
        "extract": "== History == Built in 1925. == Architecture == It is tall."
    }}}}

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return payload

    monkeypatch.setattr(tools.requests, "get", lambda *a, **k: _Resp())
    result = tools.area_history("Some Hotel")
    assert "==" not in result
    assert result == "Built in 1925. It is tall."


def _overpass_resp(elements):
    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"elements": elements}
    return _Resp()


def test_nearby_pois_drops_closed_businesses(monkeypatch):
    elements = [
        {"lat": 1.0, "lon": 2.0, "tags": {"name": "Live Cafe", "amenity": "cafe"}},
        {"lat": 1.0, "lon": 2.0, "tags": {"name": "Galeto Mania (permanentemente fechado)",
                                          "amenity": "restaurant"}},
        {"lat": 1.0, "lon": 2.0, "tags": {"name": "Old Shop", "disused:shop": "supermarket"}},
    ]
    monkeypatch.setattr(tools, "_overpass_request", lambda q: _overpass_resp(elements))
    names = [p["name"] for p in tools.nearby_pois(0.0, 0.0)]
    assert names == ["Live Cafe"]
