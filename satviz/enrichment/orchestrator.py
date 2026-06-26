"""Builds an Enrichment for a location. Structured geographic facts (Wikipedia, POIs,
weather/elevation) are gathered directly from coordinates; the lfm2.5 agent runs a
tool-using loop with web search to add broader context and a written summary.

Every source is isolated: a failure is recorded in Enrichment.errors and the rest of the
report still returns."""

import logging
import re
from time import perf_counter

import ollama

from satviz import config
from satviz.enrichment import tools
from satviz.models import Enrichment, ImageResult, VisionInsight

logger = logging.getLogger(__name__)

_MAX_TOOL_ITERS = 4

_AGENT_SYSTEM = (
    "You are a geography research assistant. You are given an AUTHORITATIVE location label "
    "and sometimes a nearby Wikipedia article — treat these as the truth for WHERE this is. "
    "NEVER infer or guess a place name, town, or country from raw latitude/longitude numbers; "
    "if you are tempted to, stop and rely only on the provided label. The satellite "
    "observation is a machine-vision hypothesis that may be wrong: confirm what matches and "
    "correct what does not. If the location is open water or a remote area with no "
    "settlement, say so plainly and describe the natural setting rather than inventing nearby "
    "towns. Search using the place name or notable features, never raw coordinates. Keep "
    "searches focused, then write 2-4 vivid, grounded sentences. Do not fabricate."
)

_REMOTE_LABELS = ("Open water or remote area",)


def _is_located(display_name: str) -> bool:
    return bool(display_name) and display_name not in _REMOTE_LABELS \
        and "not found" not in display_name.lower()


def enrich(image: ImageResult, vision: VisionInsight) -> Enrichment:
    loc = image.location
    enrichment = Enrichment()
    located = _is_located(loc.display_name)

    enrichment.wikipedia = _safe(
        enrichment, "wikipedia", lambda: tools.wikipedia_nearby(loc.latitude, loc.longitude)
    ) or {}
    enrichment.pois = _safe(
        enrichment, "pois", lambda: tools.nearby_pois(loc.latitude, loc.longitude)
    ) or []
    weather = _safe(
        enrichment, "weather", lambda: tools.weather_and_elevation(loc.latitude, loc.longitude)
    ) or {}
    if weather:
        enrichment.elevation_m = weather.pop("elevation_m", None)
        enrichment.weather = weather

    enrichment.events = _safe(
        enrichment, "events", lambda: tools.natural_events(loc.latitude, loc.longitude)
    ) or []

    wiki_title = (enrichment.wikipedia or {}).get("title", "")
    if wiki_title:
        enrichment.history = _safe(enrichment, "history", lambda: tools.area_history(wiki_title)) or ""

    if located:
        label = wiki_title or loc.display_name.split(",")[0]
        news = _safe(enrichment, "news", lambda: tools.recent_news(label, loc.display_name)) or {}
        enrichment.news = news.get("results", [])
        enrichment.news_summary = news.get("summary", "")

    web, summary = _run_agent(loc.display_name, vision.summary, wiki_title, located)
    enrichment.web = web
    enrichment.summary = summary
    return enrichment


def _safe(enrichment: Enrichment, name: str, fn):
    """Run a source; on failure record the error and return None."""
    t0 = perf_counter()
    try:
        result = fn()
        logger.info("Enrichment source '%s' ok in %d ms", name, int((perf_counter() - t0) * 1000))
        return result
    except Exception as exc:
        logger.warning("Enrichment source '%s' failed: %s", name, exc)
        enrichment.errors.append(f"{name}: {_sanitize_error(exc)}")
        return None


def _sanitize_error(exc: Exception) -> str:
    """User-facing error text: strip request URLs so coordinates and internal
    endpoints never leak into the sidebar. The full exception is logged separately."""
    msg = re.sub(r"\s*for url:\s*\S+", "", str(exc))
    return re.sub(r"https?://\S+", "", msg).strip()


def _run_agent(place: str, vision_summary: str, wiki_title: str, located: bool) -> tuple[list[dict], str]:
    """Run the lfm2.5 tool-calling loop. Returns (web_results, summary). Degrades to
    ([], '') if the model or tool is unavailable. The agent is anchored to the authoritative
    location label so it cannot confabulate a place from coordinates."""
    available = {"search_web": tools.search_web}
    anchor_lines = [f"Authoritative location: {place}."]
    if wiki_title:
        anchor_lines.append(f"Nearby Wikipedia article: {wiki_title}.")
    if not located:
        anchor_lines.append("This is open water or a remote area with little human presence; "
                            "do not invent nearby towns.")
    messages = [
        {"role": "system", "content": _AGENT_SYSTEM},
        {
            "role": "user",
            "content": (
                "\n".join(anchor_lines) + "\n"
                f"Satellite observation (hypothesis, may be wrong): {vision_summary or 'n/a'}.\n"
                "Research what is notable here and write a short, grounded context summary. "
                "Search by place name or features, not coordinates."
            ),
        },
    ]
    collected: list[dict] = []
    try:
        for _ in range(_MAX_TOOL_ITERS):
            response = ollama.chat(
                model=config.AGENT_MODEL,
                messages=messages,
                tools=[tools.search_web],
                options={"temperature": 0.3},
            )
            msg = response["message"]
            messages.append(msg)
            calls = msg.get("tool_calls") or []
            if not calls:
                return collected, (msg.get("content") or "").strip()
            for call in calls:
                name = call["function"]["name"]
                fn = available.get(name)
                if not fn:
                    continue
                logger.info("Agent tool call: %s(%s)", name, call["function"]["arguments"])
                try:
                    result = fn(**call["function"]["arguments"])
                    if isinstance(result, list):
                        collected.extend(result)
                except Exception as exc:
                    logger.warning("Agent tool '%s' failed: %s", name, exc)
                    result = f"tool error: {exc}"
                messages.append({
                    "role": "tool",
                    "content": str(result)[:4000],
                    "tool_name": call["function"]["name"],
                })
        # Out of iterations: ask for a final summary with no tools.
        final = ollama.chat(model=config.AGENT_MODEL, messages=messages,
                            options={"temperature": 0.3})
        return collected, (final["message"].get("content") or "").strip()
    except Exception as exc:
        return collected, f"(enrichment agent unavailable: {exc})"
