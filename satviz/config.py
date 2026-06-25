"""Central configuration. All identifiers and tunables come from the environment / .env
so that no personal data lives in source and the repo can be public."""

import os
from dotenv import load_dotenv

load_dotenv()  # load .env if present; does not override real environment variables


def _get(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    return value


GEE_PROJECT = _get("GEE_PROJECT")
NOMINATIM_AGENT = _get("NOMINATIM_AGENT", "satellite-insight-engine")
OLLAMA_API_KEY = _get("OLLAMA_API_KEY")  # optional; enables hosted web search

VISION_MODEL = _get("VISION_MODEL", "minicpm-v4.5:q8_0")
AGENT_MODEL = _get("AGENT_MODEL", "lfm2.5:latest")

RETENTION_DAYS = int(_get("RETENTION_DAYS", "30"))
DEFAULT_BUFFER = int(_get("DEFAULT_BUFFER", "2500"))

OUTPUT_ROOT = _get("OUTPUT_ROOT", "output_images")


def require_gee_project() -> str:
    if not GEE_PROJECT:
        raise RuntimeError(
            "GEE_PROJECT is not set. Copy .env.example to .env and set your "
            "Google Earth Engine project id."
        )
    return GEE_PROJECT


def has_hosted_search() -> bool:
    return bool(OLLAMA_API_KEY)
