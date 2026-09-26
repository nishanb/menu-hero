"""Aggregates every route module under one router (mounted at ``settings.api_prefix``).

Unversioned routes (``/api/health``, ``/api/agents``) predate the versioned surface and
stay where they are. Everything new is mounted under ``/api/v1`` so the management app has
a stable contract to build against.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    agents,
    auth,
    categories,
    floor_plans,
    google_business,
    health,
    images,
    menu,
    orders,
    public,
    tenants,
    users,
)

v1_router = APIRouter(prefix="/v1")
v1_router.include_router(auth.router, tags=["auth"])
v1_router.include_router(tenants.router, tags=["tenants"])
v1_router.include_router(floor_plans.router, tags=["floor-plans"])
v1_router.include_router(categories.router, tags=["categories"])
v1_router.include_router(menu.router, tags=["menu"])
v1_router.include_router(images.router, tags=["images"])
v1_router.include_router(orders.router, tags=["orders"])
v1_router.include_router(public.router, tags=["public"])
v1_router.include_router(google_business.router, tags=["google-business"])
v1_router.include_router(users.router, tags=["users"])

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(agents.router, tags=["agents"])
api_router.include_router(v1_router)
