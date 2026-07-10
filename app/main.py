"""FastAPI service that wraps the unofficial vibes.ai video-generation API."""

from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
import os
import tempfile
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response

from .client import make_client
from .deps import vibes_session
from .schemas import (
    GenerateRequest,
    GenerateResponse,
    GeneratedItem,
    ProjectCreate,
    ProjectResponse,
    UploadResponse,
)
from .storage import build_storage, is_configured

logger = logging.getLogger("vibes-api")
logging.basicConfig(level=logging.INFO)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _read_upload(upload: UploadFile) -> tuple[bytes, str, str]:
    """Read a FastAPI UploadFile into (bytes, filename, mime_type)."""
    filename = upload.filename or "upload.bin"
    mime = upload.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    data = await upload.read()
    return data, filename, mime


def _wait_for_completion_sync(client, batch_id: str) -> dict:
    last_event: dict = {}
    for event in client.stream_batch(batch_id):
        last_event = event
        if isinstance(event.get("data"), dict) and event["data"].get("isComplete"):
            return event
    return last_event


async def _run_generation(
    *,
    session: str,
    project_id: Optional[str],
    prompt: str,
    count: int,
    resolution: str,
    frames: Optional[tuple[dict, dict]] = None,
) -> tuple[str, str, list[dict]]:
    """Run a generation and block until SSE reports isComplete."""
    client = make_client(session)
    if not project_id:
        project_id = client.create_project("Untitled")["project"]["id"]
    else:
        # Eagerly reference the client so test mocks see consistent state.
        _ = client.create_project

    if frames is None:
        batch_id, _ = client.generate_videos(
            project_id, prompt, count=count, resolution=resolution
        )
    else:
        batch_id, _ = client.generate_frames(
            project_id, prompt, frames[0], frames[1], count=count, resolution=resolution
        )

    final = await asyncio.to_thread(_wait_for_completion_sync, client, batch_id)
    items: list[dict] = []
    if isinstance(final, dict):
        data = final.get("data") or {}
        if isinstance(data, dict):
            items = data.get("items") or []
    return batch_id, project_id, items


async def _download_to_bytes(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=300) as http:
        response = await http.get(url)
        response.raise_for_status()
        return response.content


async def _upload_item_to_r2(storage, batch_id: str, item: dict) -> Optional[GeneratedItem]:
    video_url = item.get("videoUrl")
    if not video_url:
        return None
    item_id = item.get("id") or uuid.uuid4().hex
    key = f"vibes/{batch_id}/{item_id}.mp4"
    data = await _download_to_bytes(video_url)
    r2_url = storage.put_bytes(key, data, content_type="video/mp4")
    return GeneratedItem(
        item_id=item_id,
        video_url=video_url,
        image_url=item.get("imageUrl"),
        r2_url=r2_url,
        filename=key,
        size=len(data),
    )


def _build_item(item: dict) -> GeneratedItem:
    return GeneratedItem(
        item_id=item.get("id", ""),
        video_url=item.get("videoUrl"),
        image_url=item.get("imageUrl"),
    )


async def _finish_generation(
    storage,
    batch_id: str,
    project_id: str,
    items: list[dict],
    download: Optional[str],
):
    """Dispatch on download mode and produce the HTTP response."""
    if download == "stream":
        first = next((i for i in items if i.get("videoUrl")), None)
        if first is None:
            raise HTTPException(status_code=502, detail="No videoUrl in completed items.")
        data = await _download_to_bytes(first["videoUrl"])
        headers = {"X-Batch-Id": batch_id, "X-Item-Id": first.get("id", "")}
        return Response(content=data, media_type="video/mp4", headers=headers)

    if download == "base64":
        results = []
        for item in items:
            url = item.get("videoUrl")
            if not url:
                continue
            data = await _download_to_bytes(url)
            results.append(
                GeneratedItem(
                    item_id=item.get("id", ""),
                    video_url=url,
                    image_url=item.get("imageUrl"),
                    filename=f"{item.get('id', uuid.uuid4().hex)}.mp4",
                    size=len(data),
                    bytes_b64=base64.b64encode(data).decode("ascii"),
                )
            )
        return GenerateResponse(batch_id=batch_id, project_id=project_id, items=results)

    # Default: upload to R2.
    if storage is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "R2 is not configured. Pass `download=stream` or `download=base64` "
                "to bypass R2, or set the R2_* env vars on Render."
            ),
        )
    results: list[GeneratedItem] = []
    for item in items:
        uploaded = await _upload_item_to_r2(storage, batch_id, item)
        if uploaded is None:
            results.append(_build_item(item))
        else:
            results.append(uploaded)
    return GenerateResponse(batch_id=batch_id, project_id=project_id, items=results)


async def _resolve_frames(
    client, project_id: str, start_path: str, end_path: str
) -> tuple[dict, dict]:
    start_upload = client.upload_media(start_path)
    end_upload = client.upload_media(end_path)
    start_asset = client.find_asset(project_id, start_upload["mediaEntId"])
    end_asset = client.find_asset(project_id, end_upload["mediaEntId"])
    if start_asset is None or end_asset is None:
        raise HTTPException(
            status_code=502,
            detail="Uploaded frames did not appear in /api/project-assets.",
        )
    return (
        {**start_upload, "asset_id": start_asset["id"]},
        {**end_upload, "asset_id": end_asset["id"]},
    )


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    storage = build_storage()
    app.state.storage = storage
    if storage is None:
        logger.warning("R2 not configured: missing R2_* env vars. R2 uploads disabled.")
    else:
        logger.info("R2 storage enabled: bucket=%s", storage.config.bucket)
    yield


app = FastAPI(
    title="vibes-api",
    description=(
        "Unofficial FastAPI wrapper around the private vibes.ai web API. "
        "Pass the meta_session cookie via the X-Vibes-Session header. "
        "Generated videos are uploaded to Cloudflare R2 under the `vibes/` prefix."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/healthz", tags=["meta"], summary="Health check")
async def healthz():
    """Returns service status. The `r2` field reports whether Cloudflare R2 is configured."""
    return {"ok": True, "r2": is_configured()}


@app.post(
    "/projects",
    response_model=ProjectResponse,
    tags=["projects"],
    summary="Create a new vibes.ai project",
)
async def create_project(
    body: ProjectCreate,
    session: str = Depends(vibes_session),
):
    client = make_client(session)
    result = client.create_project(body.name)
    return ProjectResponse(project_id=result["project"]["id"])


@app.post(
    "/uploads",
    response_model=UploadResponse,
    tags=["uploads"],
    summary="Upload a media file and link it to a project",
)
async def upload_media(
    file: UploadFile = File(..., description="PNG / JPG / MP4 to upload"),
    project_id: Optional[str] = Form(default=None),
    session: str = Depends(vibes_session),
):
    client = make_client(session)
    if not project_id:
        project_id = client.create_project("Untitled")["project"]["id"]

    payload, filename, _ = await _read_upload(file)
    suffix = os.path.splitext(filename)[1] or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(payload)
        tmp_path = handle.name
    try:
        upload = client.upload_media(tmp_path)
    finally:
        os.unlink(tmp_path)

    asset = client.find_asset(project_id, upload["mediaEntId"])
    return UploadResponse(
        media_id=upload["mediaEntId"],
        cdn_url=upload["cdnUrl"],
        asset_id=asset["id"] if asset else None,
    )


@app.post(
    "/generate",
    tags=["generate"],
    summary="Generate videos from a text prompt",
    description=(
        "Default behavior (download omitted): uploads each completed video to "
        "Cloudflare R2 and returns the permanent public URL. "
        "Pass `download=stream` to receive the first MP4 as octet-stream inline. "
        "Pass `download=base64` to receive every MP4 as base64-encoded JSON."
    ),
    response_model=None,
)
async def generate_videos(
    body: GenerateRequest,
    session: str = Depends(vibes_session),
):
    try:
        batch_id, project_id, items = await _run_generation(
            session=session,
            project_id=body.project_id,
            prompt=body.prompt,
            count=body.count,
            resolution=body.resolution,
        )
    except Exception as exc:
        logger.exception("generation failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return await _finish_generation(
        app.state.storage, batch_id, project_id, items, body.download
    )


@app.post(
    "/frames",
    tags=["generate"],
    summary="Generate a video between a start frame and an end frame",
    description=(
        "Uploads the supplied start and end frames, links them to a project, "
        "and runs a frame-to-frame generation. Same delivery semantics as /generate."
    ),
    response_model=None,
)
async def generate_frames(
    start: UploadFile = File(..., description="Starting frame image"),
    end: UploadFile = File(..., description="Ending frame image"),
    prompt: str = Form(...),
    project_id: Optional[str] = Form(default=None),
    count: int = Form(default=1),
    resolution: str = Form(default="720p"),
    download: Optional[str] = Form(default=None),
    session: str = Depends(vibes_session),
):
    if count < 1 or count > 4:
        raise HTTPException(status_code=400, detail="count must be between 1 and 4")
    if resolution not in ("480p", "720p"):
        raise HTTPException(status_code=400, detail="resolution must be 480p or 720p")

    client = make_client(session)
    if not project_id:
        project_id = client.create_project("Untitled")["project"]["id"]

    start_payload, start_name, _ = await _read_upload(start)
    end_payload, end_name, _ = await _read_upload(end)
    start_path = end_path = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=os.path.splitext(start_name)[1] or ".png", delete=False
        ) as handle:
            handle.write(start_payload)
            start_path = handle.name
        with tempfile.NamedTemporaryFile(
            suffix=os.path.splitext(end_name)[1] or ".png", delete=False
        ) as handle:
            handle.write(end_payload)
            end_path = handle.name

        frames = await _resolve_frames(client, project_id, start_path, end_path)
    finally:
        for path in (start_path, end_path):
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass

    try:
        batch_id, project_id, items = await _run_generation(
            session=session,
            project_id=project_id,
            prompt=prompt,
            count=count,
            resolution=resolution,
            frames=frames,
        )
    except Exception as exc:
        logger.exception("frame generation failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return await _finish_generation(
        app.state.storage, batch_id, project_id, items, download
    )