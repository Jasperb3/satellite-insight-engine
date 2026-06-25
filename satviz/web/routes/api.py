"""API / fragment routes. Action endpoints return the rendered report partial (HTMX or
JS swaps it into the panel); the partial embeds the run-data the map JS reads."""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

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


@router.get("/geocode")
def geocode(request: Request, place: str = ""):
    """Resolve a place name to coordinates so the map can 'fly to' it — no analysis."""
    location = _service(request).geocode(place)
    if location is None:
        return JSONResponse({"ok": False, "error": f"Could not find '{place}'."}, status_code=404)
    return JSONResponse({
        "ok": True,
        "latitude": location.latitude,
        "longitude": location.longitude,
        "display_name": location.display_name,
    })


@router.post("/analyze")
def analyze(request: Request, latitude: float = Form(...), longitude: float = Form(...),
            buffer_m: int = Form(...)):
    return _render(request, _service(request).analyze(latitude, longitude, buffer_m))


@router.get("/run/{run_id}")
def get_run(request: Request, run_id: str):
    return _render(request, _service(request).get_run(run_id))
