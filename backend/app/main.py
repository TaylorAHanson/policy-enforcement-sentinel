import logging
import os
from pathlib import Path
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from app.core.config import settings
from app.api.v1.api import api_router
from app.db.session import get_engine
from app.db.base import Base
from app.db.allowlist import AllowlistModel
from app.db.sentinel_run import SentinelRunModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Log database connection info loudly on startup
try:
    from app.db.session import get_database_url
    db_url = get_database_url()
    logger.info("==================================================")
    if "sqlite" in db_url:
        logger.info(f"🟢 DATABASE MODE: Using SQLite (Dev/Fallback)")
        logger.info(f"🟢 DB URL: {db_url}")
    elif "postgresql" in db_url:
        logger.info(f"🔵 DATABASE MODE: Using LAKEBASE (PostgreSQL)")
        # Mask password in URL
        safe_url = db_url
        if "@" in safe_url and ":" in safe_url:
            parts = safe_url.split("@")
            auth_part = parts[0]
            if ":" in auth_part.replace("postgresql://", ""):
                prefix, auth = auth_part.split("://")
                user, _ = auth.split(":")
                safe_url = f"{prefix}://{user}:***@{parts[1]}"
        logger.info(f"🔵 DB URL: {safe_url}")
    logger.info("==================================================")
except Exception as e:
    logger.error(f"Failed to log database URL: {e}")

# Create tables
Base.metadata.create_all(bind=get_engine())

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    redirect_slashes=False,
)

# Static directory definition
STATIC_DIR = Path(__file__).parent.parent / "static"

@app.exception_handler(404)
async def spa_fallback_handler(request: Request, exc):
    """
    Catch-all 404 handler to support SPA deep linking.
    If a route isn't found, we serve index.html unless it's an API route.
    """
    path = request.url.path
    
    # Don't intercept API or health routes - let them return real 404s
    if path.startswith("/api/") or path == "/health" or path.startswith("/.auth/"):
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": "Not found"}
        )
    
    # If the file exists physically in static folder, serve it
    local_path = STATIC_DIR / path.lstrip("/")
    if local_path.exists() and local_path.is_file():
        return FileResponse(str(local_path))
    
    # Fallback to index.html for all other routes
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": "Frontend not found"}
    )

# CORS
if settings.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS.split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_V1_PREFIX)

# Mount MCP Server (SSE)
try:
    from app.mcp_server import mcp
    app.mount("/mcp", mcp.sse_app())
    logging.info("Mounted MCP Server at /mcp")
except Exception as e:
    logging.warning(f"Failed to mount MCP Server: {e}")

@app.on_event("startup")
async def startup_event():
    import asyncio
    from app.workers.scheduler import start_scheduler
    asyncio.create_task(start_scheduler())

@app.get("/health")
def health_check():
    return {"status": "ok"}

# Static file serving for frontend
if STATIC_DIR.exists():
    logging.info(f"Serving static files from: {STATIC_DIR}")
    
    # Mount static assets (JS, CSS, images)
    assets_dir = STATIC_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
    
    # Serve index.html for the root
    @app.get("/")
    async def serve_root():
        """Serve the SPA frontend."""
        index_path = STATIC_DIR / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return {"status": "ok", "message": "API", "frontend": "index.html not found"}
else:
    logging.info("Static directory not found - running in API-only mode")
    
    @app.get("/")
    async def root():
        """Health check endpoint (API-only mode)."""
        return {
            "status": "ok",
            "message": "API is running",
            "platform": "Databricks App",
            "frontend": "Not deployed - static directory not found"
        }
