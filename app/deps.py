"""FastAPI dependencies, primarily the X-Vibes-Session header."""

from fastapi import Header, HTTPException, status


def vibes_session(x_vibes_session: str | None = Header(default=None)) -> str:
    """Extract the meta_session cookie from the X-Vibes-Session header."""
    if not x_vibes_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Vibes-Session header. Pass the meta_session cookie value.",
        )
    return x_vibes_session