from satviz.models import Enrichment, ImageResult, Location, VisionFeature, VisionInsight
from satviz.report import build_report, render_markdown


def _image():
    return ImageResult(
        image_path="/tmp/x.jpg",
        location=Location(51.5, -0.12, "London, UK"),
        buffer=2500,
    )


def test_build_report_merges_parts():
    vision = VisionInsight(land_cover=["urban"], summary="A dense city.")
    enrichment = Enrichment(summary="Capital of the UK.")
    report = build_report(_image(), vision, enrichment)
    assert report.location.display_name == "London, UK"
    assert report.vision.summary == "A dense city."
    assert report.enrichment.summary == "Capital of the UK."


def test_render_markdown_includes_key_sections():
    vision = VisionInsight(
        land_cover=["urban", "water"],
        features=[VisionFeature("river", 0.9)],
        summary="A city on a river.",
    )
    enrichment = Enrichment(
        wikipedia={"title": "London", "extract": "Capital city."},
        pois=[{"name": "Heathrow", "kind": "aerodrome"}],
        weather={"temperature": 18},
        elevation_m=11.0,
        summary="Major global city.",
    )
    md = render_markdown(build_report(_image(), vision, enrichment))
    assert "# Satellite report — London, UK" in md
    assert "A city on a river." in md
    assert "river (High)" in md
    assert "London" in md and "Capital city." in md
    assert "Heathrow" in md
    assert "elevation 11 m" in md


def test_render_markdown_handles_empty_enrichment():
    md = render_markdown(build_report(_image(), VisionInsight(summary="x"), Enrichment()))
    assert "## On the Ground" in md
