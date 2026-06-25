"""Page route (app shell) and asset serving by run_id (so the browser never sees the
on-disk output layout)."""

import math
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "index.html", {})


_PER_PAGE = 24


@router.get("/history", response_class=HTMLResponse)
def history(request: Request, page: int = 1, q: str = "", tier: str = ""):
    service = request.app.state.service
    templates = request.app.state.templates
    page = max(1, page)
    runs, total = service.list_runs(limit=_PER_PAGE, offset=(page - 1) * _PER_PAGE,
                                    query=q.strip(), tier=tier)
    return templates.TemplateResponse(request, "history.html", {
        "runs": runs,
        "total": total,
        "page": page,
        "pages": max(1, math.ceil(total / _PER_PAGE)),
        "q": q.strip(),
        "tier": tier,
        "tiers": service.run_tiers(),
        "points": service.run_points(),
    })


@router.get("/asset/{run_id}/image")
def asset_image(request: Request, run_id: str):
    path = request.app.state.service.image_path_for(run_id)
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path, media_type="image/jpeg")
