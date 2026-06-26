"""On-disk layout owner. One Storage instance per session writes all of that session's
images and reports under output_images/YYYY-MM-DD/HHMMSS/. Also purges old runs."""

import json
import os
import shutil
from datetime import datetime, timedelta
from uuid import uuid4

from satviz import config
from satviz.models import Report
from satviz.report import render_markdown


class Storage:
    def __init__(self, root: str | None = None, now: datetime | None = None):
        self.root = root or config.OUTPUT_ROOT
        stamp = now or datetime.now()
        day = stamp.strftime("%Y-%m-%d")
        tod = stamp.strftime("%H%M%S")
        base = os.path.join(self.root, day, tod)
        # Disambiguate runs that start in the same second (e.g. rapid browser clicks).
        suffix = ""
        while os.path.exists(base + suffix):
            suffix = "-" + uuid4().hex[:4]
        self.run_dir = base + suffix
        os.makedirs(self.run_dir, exist_ok=True)
        # URL-safe, reversible identifier: "<day>_<tod[suffix]>".
        self.run_id = f"{day}_{tod}{suffix}"

    @classmethod
    def resolve_run_dir(cls, run_id: str, root: str | None = None) -> str:
        """Map a run_id back to its directory without exposing the layout to callers."""
        root = root or config.OUTPUT_ROOT
        day, _, rest = run_id.partition("_")
        return os.path.join(root, day, rest)

    @staticmethod
    def find_image(run_dir: str) -> str | None:
        if not os.path.isdir(run_dir):
            return None
        for name in sorted(os.listdir(run_dir)):
            if name.endswith(".jpg"):
                return os.path.join(run_dir, name)
        return None

    @staticmethod
    def find_report_json(run_dir: str) -> str | None:
        if not os.path.isdir(run_dir):
            return None
        for name in sorted(os.listdir(run_dir)):
            if name.endswith(".json"):
                return os.path.join(run_dir, name)
        return None

    @staticmethod
    def find_report_md(run_dir: str) -> str | None:
        if not os.path.isdir(run_dir):
            return None
        for name in sorted(os.listdir(run_dir)):
            if name.endswith(".report.md"):
                return os.path.join(run_dir, name)
        return None

    def path_for(self, latitude: float, longitude: float, buffer: int) -> str:
        """Output path for a fetched image within this run's folder."""
        return os.path.join(self.run_dir, f"{latitude:.4f}-{longitude:.4f}-{buffer}m.jpg")

    def write_report(self, report: Report) -> tuple[str, str]:
        """Write the structured JSON and the readable report.md next to the image.
        Returns (json_path, markdown_path)."""
        base = os.path.splitext(report.image_path)[0]
        json_path = f"{base}.json"
        md_path = f"{base}.report.md"
        with open(json_path, "w") as handle:
            json.dump(report.to_dict(), handle, indent=4)
        with open(md_path, "w") as handle:
            handle.write(render_markdown(report))
        return json_path, md_path


def purge_old_runs(root: str | None = None, retention_days: int | None = None,
                   now: datetime | None = None) -> list[str]:
    """Delete date folders (YYYY-MM-DD) older than the retention window. Returns the list
    of removed directories."""
    root = root or config.OUTPUT_ROOT
    retention_days = config.RETENTION_DAYS if retention_days is None else retention_days
    now = now or datetime.now()
    cutoff = (now - timedelta(days=retention_days)).date()

    removed: list[str] = []
    if not os.path.isdir(root):
        return removed

    for name in os.listdir(root):
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        try:
            folder_date = datetime.strptime(name, "%Y-%m-%d").date()
        except ValueError:
            continue  # not a date-named folder; leave it alone
        if folder_date < cutoff:
            shutil.rmtree(path)
            removed.append(path)
    return removed
