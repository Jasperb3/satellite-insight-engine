"""Builds an Enrichment for a location. Structured geographic facts (Wikipedia, POIs,
weather/elevation) are gathered directly from coordinates; the lfm2.5 agent runs a
tool-using loop with web search to add broader context and a written summary.

Every source is isolated: a failure is recorded in Enrichment.errors and the rest of the
report still returns."""

import ollama

from satviz import config
from satviz.enrichment import tools
from satviz.models import Enrichment, ImageResult, VisionInsight

_MAX_TOOL_ITERS = 4

_AGENT_SYSTEM = (
    "You are a geography research assistant. Using the web_search tool, find what is "
    "notable or significant about the given location and corroborate the satellite "
    "observations. Keep searches focused. When done, write 2-4 sentences of context. "
    "Do not fabricate; rely on search results."
)


def enrich(image: ImageResult, vision: VisionInsight) -> Enrichment:
    loc = image.location
    enrichment = Enrichment()

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

    web, summary = _run_agent(loc.display_name, loc.latitude, loc.longitude, vision.summary)
    enrichment.web = web
    enrichment.summary = summary
    return enrichment


def _safe(enrichment: Enrichment, name: str, fn):
    """Run a source; on failure record the error and return None."""
    try:
        return fn()
    except Exception as exc:
        enrichment.errors.append(f"{name}: {exc}")
        return None


def _run_agent(place: str, lat: float, lon: float, vision_summary: str) -> tuple[list[dict], str]:
    """Run the lfm2.5 tool-calling loop. Returns (web_results, summary). Degrades to
    ([], '') if the model or tool is unavailable."""
    available = {"search_web": tools.search_web}
    messages = [
        {"role": "system", "content": _AGENT_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Location: {place} ({lat:.4f}, {lon:.4f}).\n"
                f"Satellite observation: {vision_summary or 'n/a'}.\n"
                "Research this location's significance and write a short context summary."
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
                fn = available.get(call["function"]["name"])
                if not fn:
                    continue
                try:
                    result = fn(**call["function"]["arguments"])
                    if isinstance(result, list):
                        collected.extend(result)
                except Exception as exc:
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
