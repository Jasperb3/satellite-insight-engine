from datetime import date, timedelta

from satviz.application.cache import ResultCache, viewport_key
from satviz.application.mapping import (
    domain, is_stale, markers_from_report, pretty_kind, pretty_place, pretty_time,
    relative_age, run_data, tier_label,
)
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


def test_pretty_time_formats_run_id():
    assert pretty_time("2026-06-25_212427") == "Jun 25, 2026 · 21:24"


def test_pretty_time_passthrough_on_garbage():
    assert pretty_time("not-a-run-id") == "not-a-run-id"


def test_tier_label_maps_known_tiers():
    assert tier_label("none") == "No imagery"
    assert tier_label("regional") == "Regional"
    assert tier_label("sentinel-2") == "sentinel-2"  # unknown -> unchanged


def test_pretty_kind_humanises_osm_values():
    assert pretty_kind("fast_food") == "Fast Food"
    assert pretty_kind("post_office") == "Post Office"
    assert pretty_kind("parking_entrance") == "Car Park Entrance"  # override
    assert pretty_kind("atm") == "ATM"                             # override
    assert pretty_kind("") == ""


def test_domain_extracts_bare_host():
    assert domain("https://www.ap.org/world/x") == "ap.org"
    assert domain("http://sportingnews.com/a?b=1") == "sportingnews.com"
    assert domain("bbc.com/news") == "bbc.com"
    assert domain("") == ""


def test_pretty_place_keeps_short_names_whole():
    assert pretty_place("Yellowstone National Park, Wyoming, United States") == \
        "Yellowstone National Park, Wyoming, United States"


def test_pretty_place_trims_long_address_to_name_and_tail():
    raw = ("Brooklyn Roasting Company Tokyo International Forum, 1, Marunouchi 3, "
           "Marunouchi, Chiyoda, Tokyo, 100-0005, Japan")
    assert pretty_place(raw) == \
        "Brooklyn Roasting Company Tokyo International Forum, Tokyo, Japan"


def test_pretty_place_drops_numeric_house_and_postcode():
    raw = "2, Macquarie Street, Quay Quarter, Sydney, New South Wales, 2000, Australia"
    out = pretty_place(raw)
    assert "2000" not in out and out.startswith("Macquarie Street")
    assert out.endswith("Australia")


def test_markers_prettify_kind():
    report = {"enrichment": {"pois": [
        {"name": "A", "kind": "fast_food", "lat": 1.0, "lon": 2.0},
    ]}}
    assert markers_from_report(report)[0]["kind"] == "Fast Food"


def test_markers_carry_category_icon():
    report = {"enrichment": {"pois": [
        {"name": "Diner", "tag": "amenity", "kind": "fast_food", "lat": 1.0, "lon": 2.0},
        {"name": "Hill", "tag": "natural", "kind": "ridge", "lat": 3.0, "lon": 4.0},  # tag fallback
        {"name": "Thing", "tag": "", "kind": "", "lat": 5.0, "lon": 6.0},             # default
    ]}}
    icons = [m["icon"] for m in markers_from_report(report)]
    assert icons == ["🍔", "🌳", "📍"]


def test_relative_age_buckets():
    today = date.today()
    assert relative_age(today.isoformat()) == "today"
    assert relative_age((today - timedelta(days=1)).isoformat()) == "yesterday"
    assert relative_age((today - timedelta(days=29)).isoformat()) == "29 days ago"
    assert relative_age((today - timedelta(days=120)).isoformat()) == "4 months ago"
    assert relative_age("") == ""
    assert relative_age("not-a-date") == ""


def test_is_stale_threshold():
    today = date.today()
    assert is_stale((today - timedelta(days=120)).isoformat()) is True
    assert is_stale((today - timedelta(days=30)).isoformat()) is False
    assert is_stale("") is False


def test_run_data_shape():
    report = {"location": {"latitude": 51.0, "longitude": -1.0}, "buffer": 1500,
              "image_path": "x.jpg", "enrichment": {"pois": []}}
    data = run_data("2026-06-25_120000", report)
    assert data["image_url"] == "/asset/2026-06-25_120000/image"
    assert data["viewport"] == {"latitude": 51.0, "longitude": -1.0, "buffer_m": 1500,
                                "display_name": None}


def test_run_data_no_image_when_missing():
    report = {"location": {"latitude": 51.0, "longitude": -1.0}, "buffer": 1500,
              "image_path": None, "enrichment": {"pois": []}}
    assert run_data("2026-06-25_120000", report)["image_url"] is None


def test_get_missing_run_is_not_found(tmp_path, monkeypatch):
    from satviz import config
    monkeypatch.setattr(config, "OUTPUT_ROOT", str(tmp_path))
    result = AnalysisService().get_run("2099-01-01_000000")
    assert result.ok is False and result.failure_kind == "not_found"


def test_reverse_flags_open_water(monkeypatch):
    from satviz.application import service
    from satviz.models import Location
    monkeypatch.setattr(service, "reverse_geocode",
                        lambda lat, lon: Location(lat, lon, "Open water or remote area", {}))
    out = AnalysisService().reverse(0.0, -30.0)
    assert out["located"] is False and out["display_name"] == "Open water or remote area"


def test_reverse_flags_populated(monkeypatch):
    from satviz.application import service
    from satviz.models import Location
    monkeypatch.setattr(service, "reverse_geocode",
                        lambda lat, lon: Location(lat, lon, "10 Downing Street, London", {}))
    assert AnalysisService().reverse(51.5, -0.12)["located"] is True


def test_start_analysis_runs_job_to_done(monkeypatch):
    import time

    from satviz.application.service import AnalysisResult
    svc = AnalysisService()
    fake = AnalysisResult(ok=True, run_id="2026-06-25_120000")

    def fake_analyze(lat, lon, buf, on_stage=None, should_cancel=None):
        on_stage("imagery")
        on_stage("report")
        return fake

    monkeypatch.setattr(svc, "analyze", fake_analyze)
    job_id = svc.start_analysis(1.0, 2.0, 1500)

    for _ in range(200):
        if svc.job_status(job_id)["state"] != "running":
            break
        time.sleep(0.01)

    status = svc.job_status(job_id)
    assert status["state"] == "done"
    assert status["ok"] is True and status["run_id"] == "2026-06-25_120000"
    assert svc.job_result(job_id) is fake
    assert svc.job_status("missing-id") is None
