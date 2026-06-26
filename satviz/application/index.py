"""A lightweight SQLite index of saved runs, so the History page can paginate, search and
map runs without walking the filesystem and opening every JSON on each request (A1).

The index is a *derived cache*: the per-run JSON files remain the source of truth. New GUI
runs are added live; `reconcile()` (run at startup) syncs the index with disk — adding runs
created outside the service (e.g. the CLI) and dropping rows for purged folders. Accessed
from request and background-job threads, so all DB access is serialised behind a lock."""

import json
import logging
import os
import sqlite3
import threading

from satviz import config
from satviz.storage import Storage

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    day           TEXT NOT NULL,
    display_name  TEXT,
    latitude      REAL,
    longitude     REAL,
    buffer_m      INTEGER,
    imagery_tier  TEXT,
    imagery_date  TEXT,
    has_image     INTEGER NOT NULL DEFAULT 0
);
"""


class RunIndex:
    def __init__(self, db_path: str | None = None):
        self._path = db_path or os.path.join(config.OUTPUT_ROOT, "index.db")
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Add columns introduced after a DB was first created (older index.db files)."""
        existing = {r["name"] for r in self._conn.execute("PRAGMA table_info(runs)")}
        if "imagery_date" not in existing:
            self._conn.execute("ALTER TABLE runs ADD COLUMN imagery_date TEXT")

    # --- writes -----------------------------------------------------------------

    def add(self, run_id: str, report: dict) -> None:
        """Upsert one run from its report dict."""
        loc = report.get("location", {})
        row = (
            run_id,
            run_id.partition("_")[0],
            loc.get("display_name", run_id),
            loc.get("latitude"),
            loc.get("longitude"),
            report.get("buffer"),
            report.get("imagery_tier"),
            report.get("imagery_date"),
            1 if report.get("image_path") else 0,
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO runs (run_id, day, display_name, latitude, longitude, "
                "buffer_m, imagery_tier, imagery_date, has_image) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET "
                "display_name=excluded.display_name, latitude=excluded.latitude, "
                "longitude=excluded.longitude, buffer_m=excluded.buffer_m, "
                "imagery_tier=excluded.imagery_tier, imagery_date=excluded.imagery_date, "
                "has_image=excluded.has_image",
                row,
            )
            self._conn.commit()

    def reconcile(self, root: str | None = None) -> None:
        """Sync the index with the filesystem: add runs found on disk but missing from the
        index, and delete rows whose run folder no longer exists (purged)."""
        root = root or config.OUTPUT_ROOT
        on_disk: set[str] = set()
        if os.path.isdir(root):
            with self._lock:
                known = {r["run_id"] for r in self._conn.execute("SELECT run_id FROM runs")}
            for day in os.listdir(root):
                day_dir = os.path.join(root, day)
                if not os.path.isdir(day_dir) or "_" in day:
                    continue
                for folder in os.listdir(day_dir):
                    run_id = f"{day}_{folder}"
                    json_path = Storage.find_report_json(os.path.join(day_dir, folder))
                    if not json_path:
                        continue
                    on_disk.add(run_id)
                    if run_id not in known:
                        try:
                            with open(json_path) as handle:
                                self.add(run_id, json.load(handle))
                        except Exception as exc:
                            logger.warning("Index: could not read %s: %s", json_path, exc)

        with self._lock:
            indexed = {r["run_id"] for r in self._conn.execute("SELECT run_id FROM runs")}
            stale = indexed - on_disk
            if stale:
                self._conn.executemany("DELETE FROM runs WHERE run_id = ?",
                                       [(rid,) for rid in stale])
                self._conn.commit()
        logger.info("Run index reconciled: %d on disk, %d removed", len(on_disk), len(stale))

    # --- reads ------------------------------------------------------------------

    def search(self, limit: int = 20, offset: int = 0, query: str = "",
               tier: str = "") -> "tuple[list[dict], int]":
        """Page of runs (newest first) plus the total matching count, with optional
        case-insensitive name search and imagery-tier filter."""
        where, params = self._filter(query, tier)
        with self._lock:
            total = self._conn.execute(
                f"SELECT COUNT(*) FROM runs{where}", params).fetchone()[0]
            rows = self._conn.execute(
                f"SELECT * FROM runs{where} ORDER BY run_id DESC LIMIT ? OFFSET ?",
                (*params, limit, offset)).fetchall()
        return [dict(r) for r in rows], total

    def points(self) -> list[dict]:
        """Located runs for the history map (E10)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT run_id, display_name, latitude, longitude FROM runs "
                "WHERE latitude IS NOT NULL AND longitude IS NOT NULL "
                "ORDER BY run_id DESC").fetchall()
        return [dict(r) for r in rows]

    def tiers(self) -> list[str]:
        """Distinct imagery tiers present, for filter chips (E3)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT imagery_tier FROM runs "
                "WHERE imagery_tier IS NOT NULL AND imagery_tier != '' "
                "ORDER BY imagery_tier").fetchall()
        return [r["imagery_tier"] for r in rows]

    @staticmethod
    def _filter(query: str, tier: str) -> tuple[str, list]:
        clauses, params = [], []
        if query:
            clauses.append("display_name LIKE ?")
            params.append(f"%{query}%")
        if tier:
            clauses.append("imagery_tier = ?")
            params.append(tier)
        return (" WHERE " + " AND ".join(clauses) if clauses else ""), params
