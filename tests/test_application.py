from satviz.application.cache import ResultCache, viewport_key
from satviz.application.mapping import markers_from_report, run_data
from satviz.application.service import AnalysisService


def test_viewport_key_normalises_float_noise():
    assert viewport_key(51.17881, -1.82619, 1500) == viewport_key(51.178809, -1.826193, 1500)


def test_cache_lru_evicts_oldest():
    cache = ResultCache(capacity=2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("a")          # touch a so b is now oldest
    cache.put("c", 3)       # evicts b
    assert cache.get("b") is None
    assert cache.get("a") == 1
    assert cache.get("c") == 3


def test_markers_skip_pois_without_coordinates():
    report = {"enrichment": {"pois": [
        {"name": "A", "kind": "stone", "lat": 1.0, "lon": 2.0},
        {"name": "B", "kind": "info"},  # no coords -> skipped
    ]}}
    markers = markers_from_report(report)
    assert [m["name"] for m in markers] == ["A"]


def test_run_data_shape():
    report = {"location": {"latitude": 51.0, "longitude": -1.0},
              "buffer": 1500, "enrichment": {"pois": []}}
    data = run_data("2026-06-25_120000", report)
    assert data["image_url"] == "/asset/2026-06-25_120000/image"
    assert data["viewport"] == {"latitude": 51.0, "longitude": -1.0, "buffer_m": 1500}


def test_get_missing_run_is_not_found(tmp_path, monkeypatch):
    from satviz import config
    monkeypatch.setattr(config, "OUTPUT_ROOT", str(tmp_path))
    result = AnalysisService().get_run("2099-01-01_000000")
    assert result.ok is False and result.failure_kind == "not_found"
