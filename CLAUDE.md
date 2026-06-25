# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Satellite Insight Engine.** A user enters a place name; the app fetches satellite imagery
from Google Earth Engine, reads it with a local Ollama vision model, then enriches that
reading with live facts from Wikipedia, OpenStreetMap, weather/elevation APIs, and (when a
key is present) hosted web search via a small tool-using agent model. The merged result is a
`Report` saved as image + JSON + Markdown. Users navigate the surrounding area with
WASD/zoom.

## Running

```bash
source .venv/bin/activate
python main.py          # interactive CLI (default)
python main.py --gui    # browser GUI (FastAPI + Leaflet) on http://localhost:8000
pytest                  # test suite
```

Controls: `W/A/S/D` move, `Z/X` zoom, `Q` quit (CLI); in the GUI the Leaflet map is primary
(click-to-analyse, pan/zoom, plus arrow/WASD/ZX keys).

## Configuration & privacy

All identifiers and tunables live in a **gitignored `.env`** (see `.env.example`), loaded by
`satviz/config.py`. There are **no personal identifiers in source** — keep it that way.
Required: `GEE_PROJECT`. Optional: `OLLAMA_API_KEY` (enables hosted web search; otherwise
free fallbacks are used). `.gitignore` also excludes `.venv/`, `output_images/`, and the
local planning `docs/`.

## External Services

- **Google Earth Engine** (`ee`): requires a one-time `earthengine authenticate` and a GEE
  project (from `GEE_PROJECT`). `satviz/imagery.py` initialises lazily. **Tiered, always-return
  imagery**: for `buffer ≤ 6 km` (detailed) it tries Sentinel-2 SR (10 m, cloud-masked) →
  Landsat 8 (30 m) → NASA GIBS; for wider views (regional) it uses NASA GIBS MODIS true-colour
  (~250 m, WMS, no key). If every tier fails the report is still produced with no image.
  Provenance (`imagery_tier`/`imagery_source`/`resolution_m`/`imagery_date`) flows into the
  `Report` and a sidebar badge; the vision prompt switches between detailed and regional modes.
- **Ollama**: `minicpm-v4.5:q8_0` (vision) and `lfm2.5` (enrichment agent) must be pulled.
- **Nominatim (OSM)**: forward + reverse geocoding (`satviz/geocode.py`), user agent from
  `NOMINATIM_AGENT`. Open water / remote points are labelled "Open water or remote area" and
  the agent is forbidden from inventing a place name from raw coordinates.
- **Enrichment APIs** (`satviz/enrichment/tools.py`): Wikipedia REST/geosearch + history
  extract, Overpass POIs (with mirror fallback), Open-Meteo (weather + elevation, keyless),
  Tavily recent news (`TAVILY_API_KEY`), NASA EONET natural events (no key), and Ollama hosted
  web search with a Wikipedia free fallback. Every source is isolated; failures degrade.

## Architecture

The codebase is the `satviz/` package built around a **UI-agnostic engine**.
`SatVizEngine.analyze_*` (in `engine.py`) orchestrates geocode → imagery → vision →
enrichment → report and **returns a `Report`** — it does no printing and opens no windows.
Presenters are thin frontends over this seam.

| Module | Role |
|---|---|
| `config.py` | Loads `.env`; single source of identifiers/tunables |
| `models.py` | Dataclasses: `Location`, `ImageResult`, `VisionInsight`, `Enrichment`, `Report` |
| `geocode.py` | Nominatim forward + reverse geocoding |
| `imagery.py` | GEE: one `_composite_and_export(...)` helper + place/coordinate wrappers |
| `vision.py` | `minicpm-v4.5` — structured JSON + narrative reading → `VisionInsight` |
| `enrichment/` | `lfm2.5` tool loop + Wikipedia/OSM/Open-Meteo/web tools → `Enrichment` |
| `report.py` | Merges vision + enrichment → `Report`; renders `report.md` |
| `storage.py` | Dated run folders, report writing, 30-day rolling purge |
| `navigation.py` | Pure WASD/zoom coordinate math |
| `engine.py` | `SatVizEngine` orchestration seam (returns `Report`) |
| `application/` | Browser-facing `AnalysisService`: DTOs, viewport cache, run addressing, error normalisation |
| `web/` | FastAPI app: `app.py` factory, `routes/` (pages + api), Jinja `templates/`, Leaflet+HTMX `static/` |
| `presenters/cli.py` | Terminal frontend |
| `main.py` | Argparse entry point (`--gui` launches uvicorn) |

Data flow (CLI): `cli.py` → `engine.py` → `geocode`/`imagery` → `vision` → `enrichment` →
`report` → `storage`.

Data flow (GUI): browser (Leaflet+HTMX) → `web/routes` → `application.AnalysisService` →
`engine.py` → … → `Report` → DTO → report partial. **Strict layering:** `web/` talks only to
`application/`, which talks only to the engine. No FastAPI/HTMX/Leaflet types in engine code;
the browser addresses runs by `run_id`, never by file path (`/asset/{run_id}/image`).

## Key Data Structures

`Report` is the top-level interface between the engine and presenters. It bundles
`Location`, the image path, a `VisionInsight` (land cover, features with confidence,
summary) and an `Enrichment` (wikipedia, pois, weather, elevation, web, summary, errors).
Every enrichment source is isolated — a failure is recorded in `Enrichment.errors` and the
rest of the report still returns.

## Output

Per session: `output_images/YYYY-MM-DD/HHMMSS/{lat:.4f}-{lon:.4f}-{buffer}m.{jpg,json}`,
a `.report.md`, and `run.html`. Runs older than `RETENTION_DAYS` are purged at startup.

## Browser GUI

Built as `satviz/web/` (FastAPI) over `satviz/application/` (the `AnalysisService`). It
consumes the same `SatVizEngine.analyze_* -> Report` seam — the engine was unchanged when the
GUI was added. Viewport results are cached (`application/cache.py`) so repeat viewports don't
rerun the pipeline; the design leaves a clean path to async job handling.

## Python Environment

Python 3.12, venv at `.venv/`. Dependencies pinned in `requirements.txt`
(`earthengine-api`, `ollama`, `geopy`, `Pillow`, `requests`, `python-dotenv`,
`fastapi`, `uvicorn`, `jinja2`, `python-multipart`, `pytest`).

## Planning Docs

`docs/PRD.md`, `docs/DESIGN_PLAN.md`, and `docs/BROWSER_PLAN.md` (all gitignored) capture the
product requirements and the phased plans this architecture was built from.
