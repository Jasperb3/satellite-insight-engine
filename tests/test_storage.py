import os
from datetime import datetime

from satviz.storage import Storage, purge_old_runs


def test_path_layout_uses_date_and_time(tmp_path):
    storage = Storage(root=str(tmp_path), now=datetime(2026, 6, 25, 14, 30, 5))
    assert storage.run_dir == os.path.join(str(tmp_path), "2026-06-25", "143005")
    assert os.path.isdir(storage.run_dir)

    path = storage.path_for(-0.2241, 51.8671, 2500)
    assert path == os.path.join(storage.run_dir, "-0.2241-51.8671-2500m.jpg")


def test_purge_removes_only_old_date_folders(tmp_path):
    root = str(tmp_path)
    old = os.path.join(root, "2026-01-01", "120000")
    recent = os.path.join(root, "2026-06-20", "120000")
    not_a_date = os.path.join(root, "keepme")
    for d in (old, recent, not_a_date):
        os.makedirs(d)

    now = datetime(2026, 6, 25, 0, 0, 0)
    removed = purge_old_runs(root=root, retention_days=30, now=now)

    assert os.path.join(root, "2026-01-01") in removed
    assert not os.path.exists(os.path.join(root, "2026-01-01"))
    assert os.path.exists(os.path.join(root, "2026-06-20"))
    assert os.path.exists(not_a_date)


def test_purge_on_missing_root_returns_empty(tmp_path):
    assert purge_old_runs(root=str(tmp_path / "nope"), retention_days=30) == []
