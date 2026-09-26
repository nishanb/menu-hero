"""Dependency provider for the process-wide :class:`~app.core.config.Settings`."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.core.config import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(get_settings)]
"""Route parameter annotation: ``settings: SettingsDep``."""
