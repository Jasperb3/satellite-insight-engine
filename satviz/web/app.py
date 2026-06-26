"""FastAPI application factory. Wires templates, static assets, a shared AnalysisService,
and the page/API routers."""

import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from satviz.application import AnalysisService
from satviz.application.mapping import (
    chip_label, clean_links, confidence_level, domain, is_stale, looks_obscured, pretty_kind,
    pretty_place, pretty_time, relative_age, split_sentences, tier_label,
)
from satviz.logging_setup import configure
from satviz.web.routes import api, pages

_HERE = os.path.dirname(__file__)
TEMPLATES = Jinja2Templates(directory=os.path.join(_HERE, "templates"))
TEMPLATES.env.filters["pretty_kind"] = pretty_kind
TEMPLATES.env.filters["relative_age"] = relative_age
TEMPLATES.env.filters["is_stale"] = is_stale
TEMPLATES.env.filters["pretty_time"] = pretty_time
TEMPLATES.env.filters["tier_label"] = tier_label
TEMPLATES.env.filters["domain"] = domain
TEMPLATES.env.filters["pretty_place"] = pretty_place
TEMPLATES.env.filters["split_sentences"] = split_sentences
TEMPLATES.env.filters["clean_links"] = clean_links
TEMPLATES.env.filters["looks_obscured"] = looks_obscured
TEMPLATES.env.filters["chip_label"] = chip_label
TEMPLATES.env.filters["confidence_level"] = confidence_level


def create_app() -> FastAPI:
    configure()
    app = FastAPI(title="Satellite Insight Engine")
    app.mount("/static", StaticFiles(directory=os.path.join(_HERE, "static")), name="static")

    # One service (with its cache) shared across requests.
    app.state.service = AnalysisService()
    app.state.templates = TEMPLATES

    app.include_router(pages.router)
    app.include_router(api.router)
    return app


app = create_app()
