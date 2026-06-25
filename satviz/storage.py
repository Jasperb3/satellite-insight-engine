"""On-disk layout owner. One Storage instance per session writes all of that session's
images and reports under output_images/YYYY-MM-DD/HHMMSS/. Also purges old runs."""

import json
import os
import shutil
from datetime import datetime, timedelta

from satviz import config
from satviz.models import Report
from satviz.report import render_markdown


class Storage:
    def __init__(self, root: str | None = None, now: datetime | None = None):
        self.root = root or config.OUTPUT_ROOT
        stamp = now or datetime.now()
        self.run_dir = os.path.join(
            self.root, stamp.strftime("%Y-%m-%d"), stamp.strftime("%H%M%S")
        )
        os.makedirs(self.run_dir, exist_ok=True)

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
