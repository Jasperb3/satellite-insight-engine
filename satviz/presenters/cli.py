"""Terminal presenter: the interactive place -> image -> analysis -> navigate loop.
Writes a run.html into the session folder so the image and report can be viewed richly
in a browser (no X server / desktop GUI required)."""

import html
import os

from satviz import config
from satviz.engine import SatVizEngine
from satviz.models import Report
from satviz.navigation import CONTROLS_HELP, handle_movement
from satviz.report import render_markdown
from satviz.storage import Storage, purge_old_runs


def run() -> None:
    removed = purge_old_runs()
    if removed:
        print(f"Purged {len(removed)} run folder(s) older than {config.RETENTION_DAYS} days.")

    storage = Storage()
    engine = SatVizEngine(storage)

    place = input("Enter a location to analyze: ").strip()
    report = engine.analyze_place(place, config.DEFAULT_BUFFER)
    if report is None:
        print("Failed to get image for the specified location.")
        return

    lat, lon = report.location.latitude, report.location.longitude
    buffer = report.buffer

    while True:
        _present(report, storage)
        print(CONTROLS_HELP, end="", flush=True)
        command = input().strip().lower()
        if command == "q":
            print("Exiting...")
            return

        lat, lon, buffer = handle_movement(lat, lon, buffer, command)
        new_report = engine.analyze_coordinates(lat, lon, buffer)
        if new_report is None:
            print("Failed to get image for the new coordinates.")
            continue
        report = new_report


def _present(report: Report, storage: Storage) -> None:
    loc = report.location
    print(f"\nLocation: {loc.display_name}")
    print(f"Coordinates: ({loc.latitude:.4f}, {loc.longitude:.4f})  Zoom: {report.buffer}m")
    print(f"\nImage: {report.image_path}")
    print("\nAI analysis:")
    print(report.vision.summary or "(no summary)")
    if report.vision.features:
        feats = ", ".join(
            f"{f.name} ({f.confidence:.0%})" if f.confidence else f.name
            for f in report.vision.features
        )
        print(f"Features: {feats}")
    if report.enrichment.summary:
        print("\nContext:")
        print(report.enrichment.summary)

    html_path = _write_run_html(report, storage)
    print(f"\nRich view: open {html_path} in your browser")


def _write_run_html(report: Report, storage: Storage) -> str:
    image_name = os.path.basename(report.image_path)
    body_md = render_markdown(report)
    page = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Satellite report</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:900px;margin:2rem auto;"
        "padding:0 1rem;line-height:1.5}img{max-width:100%;border-radius:6px}"
        "pre{white-space:pre-wrap;background:#f6f6f6;padding:1rem;border-radius:6px}</style>"
        "</head><body>"
        f"<img src='{html.escape(image_name)}' alt='satellite image'>"
        f"<pre>{html.escape(body_md)}</pre>"
        "</body></html>"
    )
    html_path = os.path.join(storage.run_dir, "run.html")
    with open(html_path, "w") as handle:
        handle.write(page)
    return html_path
