from fastapi import APIRouter
from app.core.config import settings

router = APIRouter()

@router.get("/")
async def get_branding():
    return {
        "name": settings.BRANDING_NAME,
        "logo_url": settings.BRANDING_LOGO_URL,
        "primary_color": settings.BRANDING_PRIMARY_COLOR,
        "secondary_color": settings.BRANDING_SECONDARY_COLOR,
    }
