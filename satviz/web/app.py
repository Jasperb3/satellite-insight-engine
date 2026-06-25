"""FastAPI application factory. Wires templates, static assets, a shared AnalysisService,
and the page/API routers."""

import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from satviz.application import AnalysisService
from satviz.logging_setup import configure
from satviz.web.routes import api, pages

_HERE = os.path.dirname(__file__)
TEMPLATES = Jinja2Templates(directory=os.path.join(_HERE, "templates"))


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
