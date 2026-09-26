"""Line ids minted on the server, for callers that have no client to mint them."""

from __future__ import annotations

from uuid import uuid4


def new_line_id() -> str:
    """A fresh order-line id, in the same shape the POS mints on the client."""
    return str(uuid4())
