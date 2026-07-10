"""Thin wrapper around the existing vibes.py client."""

from __future__ import annotations

import sys
from pathlib import Path

# vibes.py sits at the repo root next to app/.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from vibes import Vibes  # noqa: E402


def make_client(session: str) -> Vibes:
    """Construct a Vibes client with the caller-supplied meta_session cookie."""
    return Vibes(session)