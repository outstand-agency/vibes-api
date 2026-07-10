"""Cloudflare R2 storage helpers (boto3 S3-compatible client)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class R2Config:
    bucket: str
    public_url: str
    endpoint: str
    access_key_id: str
    secret_access_key: str


def load_r2_config() -> Optional[R2Config]:
    """Read R2 env vars. Returns None when any required var is missing."""
    endpoint = os.environ.get("R2_ENDPOINT", "").strip()
    access = os.environ.get("R2_ACCESS_KEY_ID", "").strip()
    secret = os.environ.get("R2_SECRET_ACCESS_KEY", "").strip()
    bucket = os.environ.get("R2_BUCKET", "remotion-assets").strip()
    public = os.environ.get("R2_PUBLIC_URL", "").strip().rstrip("/")
    if not (endpoint and access and secret and public):
        return None
    return R2Config(
        bucket=bucket,
        public_url=public,
        endpoint=endpoint,
        access_key_id=access,
        secret_access_key=secret,
    )


def is_configured() -> bool:
    return load_r2_config() is not None


class R2Storage:
    def __init__(self, config: R2Config):
        # Imported lazily so the service still boots when boto3 isn't installed.
        import boto3  # type: ignore

        self.config = config
        self.client = boto3.client(
            "s3",
            endpoint_url=config.endpoint,
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            region_name="auto",
        )

    def put_bytes(self, key: str, body: bytes, content_type: str = "video/mp4") -> str:
        self.client.put_object(
            Bucket=self.config.bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )
        return f"{self.config.public_url}/{key}"


def build_storage() -> Optional[R2Storage]:
    cfg = load_r2_config()
    if cfg is None:
        return None
    return R2Storage(cfg)