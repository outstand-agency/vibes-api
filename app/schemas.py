"""Pydantic schemas for the FastAPI service."""

from typing import Optional

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(default="Untitled", description="Project name shown in vibes.ai.")


class ProjectResponse(BaseModel):
    project_id: str


class UploadResponse(BaseModel):
    media_id: str
    cdn_url: str
    asset_id: Optional[str] = None


class GenerateRequest(BaseModel):
    prompt: str = Field(..., description="Text prompt for video generation.")
    project_id: Optional[str] = Field(
        default=None, description="Reuse an existing project; otherwise one is created."
    )
    count: int = Field(default=1, ge=1, le=4, description="Number of videos (1-4).")
    resolution: str = Field(default="720p", pattern="^(480p|720p)$")
    download: Optional[str] = Field(
        default=None,
        description="Override delivery: 'stream' returns octet-stream, 'base64' returns inline JSON.",
    )


class GeneratedItem(BaseModel):
    item_id: str
    video_url: Optional[str] = None
    image_url: Optional[str] = None
    r2_url: Optional[str] = None
    filename: Optional[str] = None
    size: Optional[int] = None
    bytes_b64: Optional[str] = None


class GenerateResponse(BaseModel):
    batch_id: str
    project_id: str
    items: list[GeneratedItem]