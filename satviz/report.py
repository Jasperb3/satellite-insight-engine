"""Merge a VisionInsight and an Enrichment into a Report, and render a readable report.md."""

from satviz.models import Enrichment, ImageResult, Report, VisionInsight


def build_report(image: ImageResult, vision: VisionInsight, enrichment: Enrichment) -> Report:
    return Report(
        location=image.location,
        buffer=image.buffer,
        image_path=image.image_path,
        vision=vision,
        enrichment=enrichment,
        image_metadata=image.image_metadata,
    )


def render_markdown(report: Report) -> str:
    loc = report.location
    v = report.vision
    e = report.enrichment

    lines: list[str] = []
    lines.append(f"# Satellite report — {loc.display_name}")
    lines.append("")
    lines.append(f"- **Coordinates:** {loc.latitude:.4f}, {loc.longitude:.4f}")
    lines.append(f"- **Zoom (buffer):** {report.buffer} m")
    lines.append(f"- **Image:** `{report.image_path}`")
    lines.append("")

    lines.append("## What the image shows")
    lines.append("")
    lines.append(v.summary or "_No summary produced._")
    lines.append("")
    if v.land_cover:
        lines.append(f"**Land cover:** {', '.join(v.land_cover)}")
        lines.append("")
    if v.features:
        lines.append("**Visible features:**")
        lines.append("")
        for feat in v.features:
            conf = f" ({feat.confidence:.0%})" if feat.confidence else ""
            lines.append(f"- {feat.name}{conf}")
        lines.append("")

    lines.append("## Context & enrichment")
    lines.append("")
    if e.summary:
        lines.append(e.summary)
        lines.append("")
    if e.wikipedia:
        title = e.wikipedia.get("title", "Wikipedia")
        extract = e.wikipedia.get("extract", "")
        lines.append(f"**{title}** — {extract}")
        lines.append("")
    if e.pois:
        lines.append("**Nearby map features (OpenStreetMap):**")
        lines.append("")
        for poi in e.pois[:15]:
            name = poi.get("name", "unnamed")
            kind = poi.get("kind", "")
            lines.append(f"- {name} ({kind})" if kind else f"- {name}")
        lines.append("")
    if e.weather or e.elevation_m is not None:
        bits = []
        if e.elevation_m is not None:
            bits.append(f"elevation {e.elevation_m:.0f} m")
        temp = e.weather.get("temperature")
        if temp is not None:
            bits.append(f"current temp {temp}°C")
        if bits:
            lines.append("**Environment:** " + ", ".join(bits))
            lines.append("")
    if e.web:
        lines.append("**From the web:**")
        lines.append("")
        for item in e.web[:5]:
            lines.append(f"- [{item.get('title', 'source')}]({item.get('url', '')})")
        lines.append("")
    if e.errors:
        lines.append("> Some sources were unavailable: " + "; ".join(e.errors))
        lines.append("")

    return "\n".join(lines)
