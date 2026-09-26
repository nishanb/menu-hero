"""Health-check response model."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Body of ``GET /api/health``: exactly ``{"status": "ok"}``."""

    model_config = ConfigDict(json_schema_extra={"examples": [{"status": "ok"}]})

    status: Literal["ok"] = "ok"
