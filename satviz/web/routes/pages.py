"""Page route (app shell) and asset serving by run_id (so the browser never sees the
on-disk output layout)."""

import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    service = request.app.state.service
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request, "index.html", {"runs": service.list_runs()},
    )


@router.get("/asset/{run_id}/image")
def asset_image(request: Request, run_id: str):
    path = request.app.state.service.image_path_for(run_id)
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path, media_type="image/jpeg")
