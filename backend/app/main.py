import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.v1.api import api_router
from app.db.session import engine
from app.db.base import Base
from app.db.allowlist import AllowlistModel

logging.basicConfig(level=logging.INFO)

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json"
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
