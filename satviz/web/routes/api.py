"""API / fragment routes. Action endpoints return the rendered report partial (HTMX or
JS swaps it into the panel); the partial embeds the run-data the map JS reads."""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from satviz.application import AnalysisResult
from satviz.application.mapping import run_data

router = APIRouter(prefix="/api")


def _service(request: Request):
    return request.app.state.service


def _render(request: Request, result: AnalysisResult) -> HTMLResponse:
    templates = request.app.state.templates
    context = {
        "result": result,
        "run_data": run_data(result.run_id, result.report) if result.ok else None,
    }
    return templates.TemplateResponse(request, "partials/report.html", context)


@router.post("/search")
def search(request: Request, place: str = Form("")):
    return _render(request, _service(request).search(place))


@router.post("/analyze")
def analyze(request: Request, latitude: float = Form(...), longitude: float = Form(...),
            buffer_m: int = Form(...)):
    return _render(request, _service(request).analyze(latitude, longitude, buffer_m))


@router.post("/move")
def move(request: Request, latitude: float = Form(...), longitude: float = Form(...),
         buffer_m: int = Form(...), command: str = Form(...)):
    return _render(request, _service(request).move(latitude, longitude, buffer_m, command))


@router.post("/zoom")
def zoom(request: Request, latitude: float = Form(...), longitude: float = Form(...),
         buffer_m: int = Form(...), command: str = Form(...)):
    # command is "z" (in) or "x" (out); navigation.py owns the buffer math.
    return _render(request, _service(request).move(latitude, longitude, buffer_m, command))


@router.get("/run/{run_id}")
def get_run(request: Request, run_id: str):
    return _render(request, _service(request).get_run(run_id))


@router.get("/runs", response_class=HTMLResponse)
def runs(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request, "partials/history.html", {"runs": _service(request).list_runs()},
    )
