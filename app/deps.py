"""FastAPI dependencies, primarily the X-Vibes-Session header.

Falls back to the VIBES_SESSION env var if the header is not sent. This lets
the deployed service run unattended once an admin sets VIBES_SESSION on Render.
"""

import os

from fastapi import Header, HTTPException, status


def vibes_session(
    x_vibes_session: str | None = Header(default=None, alias="X-Vibes-Session"),
) -> str:
    """Extract the meta_session cookie from the X-Vibes-Session header, or
    fall back to the VIBES_SESSION env var (e.g. set on Render)."""
    val = x_vibes_session or os.environ.get("VIBES_SESSION", "").strip()
    if not val:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Missing X-Vibes-Session header (and VIBES_SESSION env var is not set). "
                "Set the meta_session cookie value via the header or Render env var."
            ),
        )
    return val
