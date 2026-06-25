"""Vision-model reading of the satellite image. Asks minicpm-v4.5 for a structured JSON
block plus a prose summary in a single call, then parses it into a VisionInsight."""

import json
import logging
import re

import ollama

from satviz import config
from satviz.models import ImageResult, VisionFeature, VisionInsight

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a remote-sensing image analyst. You are shown a true-colour satellite "
    "composite of a small area. Describe only what is actually visible from above; do "
    "not invent specific place names or facts you cannot see. Express uncertainty with "
    "the confidence scores. Be precise about land cover, water, vegetation, urban "
    "density, transport, and notable man-made or natural features."
)

_INSTRUCTIONS = (
    "Analyse this satellite image. Respond with a single JSON object and nothing else, "
    "using exactly this schema:\n"
    "{\n"
    '  "land_cover": ["<dominant classes, e.g. urban, cropland, forest, water, desert>"],\n'
    '  "features": [{"name": "<visible feature>", "confidence": <0.0-1.0>}],\n'
    '  "summary": "<2-4 sentence plain-language description of the scene>"\n'
    "}"
)


def describe(image: ImageResult) -> VisionInsight:
    """Run the vision model on the image and return a structured + narrative reading."""
    loc = image.location
    prompt = (
        f"{_INSTRUCTIONS}\n\n"
        f"Context (do not over-rely on this; analyse the pixels): the image is centred "
        f"near {loc.latitude:.4f}, {loc.longitude:.4f}."
    )
    logger.info("Calling vision model %s on %s", config.VISION_MODEL, image.image_path)
    try:
        response = ollama.chat(
            model=config.VISION_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt, "images": [image.image_path]},
            ],
            options={"temperature": 0.2, "num_ctx": 8192},
        )
        content = response["message"]["content"]
    except Exception as exc:
        logger.error("Vision model error: %s", exc)
        return VisionInsight(summary=f"Vision model error: {exc}", raw_response="")

    return _parse(content)


def _parse(content: str) -> VisionInsight:
    """Parse the model output, tolerating prose or code fences around the JSON block."""
    data = _extract_json(content)
    if data is None:
        # Fall back to treating the whole response as the narrative.
        return VisionInsight(summary=content.strip(), raw_response=content)

    features = []
    for item in data.get("features", []):
        if isinstance(item, dict) and item.get("name"):
            try:
                conf = float(item.get("confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                conf = 0.0
            features.append(VisionFeature(name=str(item["name"]), confidence=conf))

    land_cover = [str(c) for c in data.get("land_cover", []) if c]
    return VisionInsight(
        land_cover=land_cover,
        features=features,
        summary=str(data.get("summary", "")).strip(),
        raw_response=content,
    )


def _extract_json(content: str) -> dict | None:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        brace = re.search(r"\{.*\}", content, re.DOTALL)
        candidate = brace.group(0) if brace else None
    if candidate is None:
        return None
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None
