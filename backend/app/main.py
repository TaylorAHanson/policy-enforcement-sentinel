import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.api import api_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_engine

# Importing the package registers every model on Base.metadata. Without it,
# create_all silently creates only the tables that happen to be imported.
import app.db  # noqa: F401

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent.parent / "static"


def _log_database_mode() -> None:
    try:
        from app.db.session import get_database_url

        db_url = get_database_url()
        if "sqlite" in db_url:
            logger.info("Database: SQLite (dev/fallback) at %s", db_url)
        elif "postgresql" in db_url:
            safe_url = db_url
            if "@" in safe_url and "://" in safe_url:
                prefix, rest = safe_url.split("://", 1)
                if ":" in rest.split("@")[0]:
                    user = rest.split(":")[0]
                    safe_url = f"{prefix}://{user}:***@{rest.split('@', 1)[1]}"
            logger.info("Database: Lakebase/PostgreSQL at %s", safe_url)
    except Exception as e:
        logger.error("Could not determine the database URL: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _log_database_mode()

    Base.metadata.create_all(bind=get_engine())

    from app.db import migrate

    migrate.run_startup_migrations()

    # DB-backed setting overrides must land before anything reads settings, and
    # this is also where the enforcement state is announced in the log.
    from app.core.settings_store import load_overrides
    from app.db.session import get_lakebase_session

    db = get_lakebase_session()
    try:
        load_overrides(db)
    except Exception as e:
        logger.error("Could not load setting overrides: %s", e)
    finally:
        db.close()

    # Policies come down from git before OPA is pointed at the directory, so the
    # server starts on the target branch rather than on whatever the image
    # happened to ship.
    from app.services import policy_sync

    result = await policy_sync.sync_policies()
    logger.info("Policy working copy: %s — %s", result.status, result.detail)

    # Embedded OPA. A failure here is not fatal — the provider falls back to the
    # CLI — but it is worth shouting about, because the fallback is 20x slower.
    if settings.OPA_EMBEDDED_ENABLED and not settings.OPA_URL:
        from app.providers.opa import server_manager

        url = await asyncio.to_thread(
            server_manager.start, settings.get_policies_dir, opa_binary=settings.OPA_BINARY
        )
        if not url:
            if settings.OPA_REQUIRE_SERVER:
                raise RuntimeError(
                    "OPA_REQUIRE_SERVER is set but the embedded OPA server failed to start."
                )
            logger.warning(
                "Embedded OPA server unavailable; falling back to per-evaluation CLI "
                "invocations. Scans will be substantially slower."
            )

    from app.workers.scheduler import start_scheduler

    scheduler_task = asyncio.create_task(start_scheduler())

    sync_task = None
    if settings.POLICY_SYNC_INTERVAL_SECONDS > 0:
        sync_task = asyncio.create_task(
            policy_sync.run_periodic_sync(settings.POLICY_SYNC_INTERVAL_SECONDS)
        )

    yield

    scheduler_task.cancel()
    if sync_task:
        sync_task.cancel()

    from app.providers.model_serving.client import close_clients as close_model_clients
    from app.providers.opa import server_manager
    from app.providers.opa.client import close_clients

    await close_clients()
    await close_model_clients()
    await asyncio.to_thread(server_manager.stop)


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    redirect_slashes=False,
    lifespan=lifespan,
)


@app.exception_handler(404)
async def spa_fallback_handler(request: Request, exc):
    """Serve index.html for unknown non-API routes so SPA deep links work."""
    path = request.url.path

    if path.startswith("/api/") or path == "/health" or path.startswith("/.auth/"):
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND, content={"detail": "Not found"}
        )

    local_path = STATIC_DIR / path.lstrip("/")
    if local_path.exists() and local_path.is_file():
        return FileResponse(str(local_path))

    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))

    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND, content={"detail": "Frontend not found"}
    )


if settings.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS.split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_V1_PREFIX)

try:
    from app.mcp_server import mcp

    app.mount("/mcp", mcp.sse_app())
    logger.info("Mounted MCP server at /mcp")
except Exception as e:
    logger.warning("Failed to mount the MCP server: %s", e)


@app.get("/health")
def health_check():
    from app.providers.opa import server_manager

    return {
        "status": "ok",
        "opa_embedded": server_manager.is_running(),
        "enforcement_enabled": bool(settings.ENFORCEMENT_ENABLED),
    }


if STATIC_DIR.exists():
    logger.info("Serving static files from %s", STATIC_DIR)

    assets_dir = STATIC_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/")
    async def serve_root():
        index_path = STATIC_DIR / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return {"status": "ok", "message": "API", "frontend": "index.html not found"}

else:
    logger.info("No static directory found; running in API-only mode.")

    @app.get("/")
    async def root():
        return {
            "status": "ok",
            "message": "API is running",
            "platform": "Databricks App",
            "frontend": "Not deployed - static directory not found",
        }
