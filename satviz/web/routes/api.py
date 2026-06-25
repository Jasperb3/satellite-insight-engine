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


@router.get("/reverse")
def reverse(request: Request, latitude: float, longitude: float):
    """Reverse-geocode a point so the UI can warn before an open-water capture — no analysis."""
    return JSONResponse(_service(request).reverse(latitude, longitude))


@router.post("/analyze")
def analyze(request: Request, latitude: float = Form(...), longitude: float = Form(...),
            buffer_m: int = Form(...)):
    return _render(request, _service(request).analyze(latitude, longitude, buffer_m))


@router.post("/analyze/start")
def analyze_start(request: Request, latitude: float = Form(...), longitude: float = Form(...),
                  buffer_m: int = Form(...)):
    """Begin a background analysis (E1/E2); returns a job id the client polls."""
    job_id = _service(request).start_analysis(latitude, longitude, buffer_m)
    return JSONResponse({"job_id": job_id})


@router.get("/analyze/status/{job_id}")
def analyze_status(request: Request, job_id: str):
    status = _service(request).job_status(job_id)
    if status is None:
        return JSONResponse({"error": "Unknown job."}, status_code=404)
    return JSONResponse(status)


@router.get("/analyze/result/{job_id}")
def analyze_result(request: Request, job_id: str):
    """Render the finished report partial for a completed job."""
    result = _service(request).job_result(job_id)
    if result is None:
        return JSONResponse({"error": "No result for this job."}, status_code=404)
    return _render(request, result)


@router.delete("/analyze/{job_id}")
def analyze_cancel(request: Request, job_id: str):
    ok = _service(request).cancel_analysis(job_id)
    return JSONResponse({"cancelled": ok}, status_code=200 if ok else 404)


@router.get("/run/{run_id}")
def get_run(request: Request, run_id: str):
    return _render(request, _service(request).get_run(run_id))
