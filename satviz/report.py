"""Merge a VisionInsight and an Enrichment into a Report, and render a readable report.md."""

from urllib.parse import urlsplit

from satviz.models import Enrichment, ImageResult, Report, VisionInsight


def _domain(url: str) -> str:
    """Bare host of a URL for a compact source label ('https://www.ap.org/x' -> 'ap.org')."""
    if not url:
        return "source"
    host = urlsplit(url if "//" in url else "//" + url).netloc.split(":")[0]
    return host[4:] if host.startswith("www.") else host or "source"


def confidence_band(confidence: float) -> str:
    """Qualitative confidence band shared by every presenter — round-number model scores
    don't warrant a false-precise percentage (B5)."""
    if confidence >= 0.8:
        return "High"
    return "Medium" if confidence >= 0.5 else "Low"


def build_report(image: ImageResult, vision: VisionInsight, enrichment: Enrichment) -> Report:
    return Report(
        location=image.location,
        buffer=image.buffer,
        image_path=image.image_path,
        vision=vision,
        enrichment=enrichment,
        imagery_tier=image.imagery_tier,
        imagery_source=image.imagery_source,
        resolution_m=image.resolution_m,
        imagery_date=image.imagery_date,
        imagery_note=image.note,
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
    if report.image_path:
        source = report.imagery_source or "imagery"
        res = f" ({report.resolution_m:.0f} m)" if report.resolution_m else ""
        date = f", {report.imagery_date}" if report.imagery_date else ""
        lines.append(f"- **Imagery:** {report.imagery_tier} — {source}{res}{date}")
        lines.append(f"- **Image:** `{report.image_path}`")
    else:
        lines.append(f"- **Imagery:** none — {report.imagery_note}")
    lines.append("")

    lines.append("## From Above")
    lines.append("")
    lines.append(v.summary or "_No summary produced._")
    lines.append("")
    if v.land_cover:
        lines.append(f"**Land cover:** {', '.join(v.land_cover)}")
        lines.append("")
    if v.features:
        lines.append("### Visible features")
        lines.append("")
        for feat in v.features:
            conf = f" ({confidence_band(feat.confidence)})" if feat.confidence else ""
            lines.append(f"- {feat.name}{conf}")
        lines.append("")

    lines.append("## On the Ground")
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
        lines.append("### Points of Interest (OpenStreetMap)")
        lines.append("")
        for poi in e.pois[:15]:
            name = poi.get("name", "unnamed")
            kind = poi.get("kind", "")
            lines.append(f"- {name} ({kind})" if kind else f"- {name}")
        lines.append("")
    if e.weather or e.elevation_m is not None:
        bits = []
        temp = e.weather.get("temperature")
        if temp is not None:
            label = e.weather.get("label", "")
            bits.append(f"{temp}°C {label}".strip())
        if e.weather.get("humidity") is not None:
            bits.append(f"humidity {e.weather['humidity']}%")
        if e.weather.get("wind_kmh") is not None:
            bits.append(f"wind {e.weather['wind_kmh']} km/h")
        if e.elevation_m is not None:
            bits.append(f"elevation {e.elevation_m:.0f} m")
        if bits:
            lines.append("**Environment:** " + ", ".join(bits))
            if e.weather.get("forecast_url"):
                lines.append(f" ([full forecast]({e.weather['forecast_url']}))")
            lines.append("")
    if e.history:
        lines.append("**History:** " + e.history)
        lines.append("")
    if e.news_summary or e.news:
        lines.append("### Recent news")
        lines.append("")
        if e.news_summary:
            lines.append(e.news_summary)
            lines.append("")
        for item in e.news[:5]:
            url = item.get("url", "")
            lines.append(f"- {item.get('title', 'source')} — [{_domain(url)}]({url})")
        lines.append("")
    if e.events:
        lines.append("### Active natural events nearby")
        lines.append("")
        for ev in e.events[:6]:
            title = ev.get("title", "event")
            category = ev.get("category", "")
            parts = [title]
            if category and category[:4].lower() not in title.lower():
                parts.append(category)
            if ev.get("date"):
                parts.append(ev["date"])
            meta = " · ".join(parts)
            url = ev.get("url", "")
            lines.append(f"- {meta}" + (f" ([details]({url}))" if url else ""))
        lines.append("")
    if e.web:
        lines.append("### Further Reading")
        lines.append("")
        for item in e.web[:5]:
            lines.append(f"- [{item.get('title', 'source')}]({item.get('url', '')})")
        lines.append("")
    if e.errors:
        lines.append("> Some sources were unavailable: " + "; ".join(e.errors))
        lines.append("")

    return "\n".join(lines)
