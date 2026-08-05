from fastapi import APIRouter

from app.api.v1.endpoints import (
    agent,
    allowlist,
    branding,
    policies,
    readme,
    release_notes,
    sentinel,
    settings,
)

api_router = APIRouter()
api_router.include_router(sentinel.router, prefix="/sentinel", tags=["sentinel"])
api_router.include_router(agent.router, prefix="/agent", tags=["agent"])
api_router.include_router(policies.router, prefix="/policies", tags=["policies"])
api_router.include_router(branding.router, prefix="/branding", tags=["branding"])
api_router.include_router(allowlist.router, prefix="/allowlist", tags=["allowlist"])
api_router.include_router(readme.router, prefix="/readme", tags=["readme"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(
    release_notes.router, prefix="/release-notes", tags=["release-notes"]
)
