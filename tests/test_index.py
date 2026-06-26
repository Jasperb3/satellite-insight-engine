"""Run index: add/upsert, paginated listing, search, tier filter, and reconcile (A1)."""

import json
import os

from satviz.application.index import RunIndex


def _report(name="Somewhere", lat=51.0, lon=-1.0, tier="detailed", image="x.jpg",
            imagery_date="2026-06-01"):
    return {"location": {"display_name": name, "latitude": lat, "longitude": lon},
            "buffer": 1500, "imagery_tier": tier, "image_path": image,
            "imagery_date": imagery_date}


def test_add_stores_imagery_date_for_stale_badge(tmp_path):
    idx = _index(tmp_path)
    idx.add("2026-06-25_120000", _report("Dated", imagery_date="2025-01-15"))
    runs, _ = idx.search()
    assert runs[0]["imagery_date"] == "2025-01-15"


def _index(tmp_path):
    return RunIndex(db_path=str(tmp_path / "index.db"))


def test_add_and_list_newest_first(tmp_path):
    idx = _index(tmp_path)
    idx.add("2026-06-24_120000", _report("Old"))
    idx.add("2026-06-25_120000", _report("New"))
    runs, total = idx.search()
    assert total == 2
    assert [r["display_name"] for r in runs] == ["New", "Old"]


def test_add_is_upsert(tmp_path):
    idx = _index(tmp_path)
    idx.add("2026-06-25_120000", _report("First"))
    idx.add("2026-06-25_120000", _report("Updated"))
    runs, total = idx.search()
    assert total == 1 and runs[0]["display_name"] == "Updated"


def test_list_pagination(tmp_path):
    idx = _index(tmp_path)
    for i in range(5):
        idx.add(f"2026-06-25_12000{i}", _report(f"Run {i}"))
    page1, total = idx.search(limit=2, offset=0)
    page2, _ = idx.search(limit=2, offset=2)
    assert total == 5 and len(page1) == 2 and len(page2) == 2
    assert page1[0]["run_id"] != page2[0]["run_id"]


def test_search_and_tier_filter(tmp_path):
    idx = _index(tmp_path)
    idx.add("2026-06-25_120001", _report("Paris", tier="detailed"))
    idx.add("2026-06-25_120002", _report("London", tier="regional"))
    runs, total = idx.search(query="par")
    assert total == 1 and runs[0]["display_name"] == "Paris"
    runs, total = idx.search(tier="regional")
    assert total == 1 and runs[0]["display_name"] == "London"
    assert idx.tiers() == ["detailed", "regional"]


def test_points_skip_unlocated(tmp_path):
    idx = _index(tmp_path)
    idx.add("2026-06-25_120001", _report("Located", lat=1.0, lon=2.0))
    idx.add("2026-06-25_120002",
            {"location": {"display_name": "No coords"}, "buffer": 1500, "image_path": None})
    points = idx.points()
    assert [p["display_name"] for p in points] == ["Located"]


def test_reconcile_adds_disk_runs_and_drops_purged(tmp_path):
    root = tmp_path / "output"
    run_dir = root / "2026-06-25" / "120000"
    os.makedirs(run_dir)
    with open(run_dir / "run.json", "w") as fh:
        json.dump(_report("From Disk"), fh)

    idx = _index(tmp_path)
    idx.add("2099-01-01_000000", _report("Ghost"))  # indexed but not on disk
    idx.reconcile(root=str(root))

    runs, total = idx.search()
    names = {r["display_name"] for r in runs}
    assert total == 1 and names == {"From Disk"}  # disk run added, ghost dropped
