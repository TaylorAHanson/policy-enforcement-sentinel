"""Database session management for Lakebase (PostgreSQL) and SQLite (dev).

Three problems this file exists to solve, all of which showed up as
intermittent failures during long scans rather than at startup:

1. **Lakebase OAuth tokens are short-lived.** A token baked into the connection
   URL at startup stops working roughly an hour later, and the failure surfaces
   as an authentication error on a connection the pool thought was fine. The
   ``do_connect`` listener fetches a fresh token for every new connection.

2. **Idle connections get dropped.** Lakebase closes connections that sit idle,
   which a long scan does between its short-lived sessions. ``pool_recycle`` and
   TCP keepalives mean the pool retires connections before the server does.

3. **``SET search_path`` does not survive a pooled rollback.** Setting it in an
   ``on_connect`` hook looked correct and worked until a transaction rolled
   back, at which point queries silently resolved against ``public``. Passing it
   as a libpq ``options`` connection parameter makes it part of the connection
   itself.
"""
import logging
import os
from typing import Generator, Optional
from urllib.parse import quote_plus

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from app.core.config import settings

logger = logging.getLogger(__name__)

_engine = None
_SessionLocal = None
_lakebase_endpoint: Optional[str] = None


def reset_database_connection():
    """Drop the engine and session factory, e.g. after credentials change."""
    global _engine, _SessionLocal
    logger.warning("Resetting database connection...")
    if _engine:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def _ensure_databricks_host_scheme() -> None:
    """Qualify the host in the environment, for libraries that read it directly.

    ``settings.DATABRICKS_HOST`` is already normalised by a validator, but the
    environment it was read from is not, and anything reaching for os.environ
    sees the bare hostname a deployed App was given.
    """
    from app.core.config import qualify_host

    env_host = os.environ.get("DATABRICKS_HOST", "")
    if env_host:
        os.environ["DATABRICKS_HOST"] = qualify_host(env_host) or env_host


def get_lakebase_token(endpoint_path: Optional[str] = None) -> Optional[str]:
    """Fetch a short-lived Postgres credential for Lakebase.

    Extracted so the ``do_connect`` listener can call it per connection rather
    than relying on whatever token happened to be valid at startup.
    """
    endpoint = endpoint_path or _lakebase_endpoint
    try:
        from databricks.sdk import WorkspaceClient

        _ensure_databricks_host_scheme()
        sdk = WorkspaceClient()

        if endpoint:
            response = sdk.api_client.do(
                "POST", "/api/2.0/postgres/credentials", body={"endpoint": endpoint}
            )
            token = response.get("token")
            if token:
                return token
            logger.error("Lakebase credentials call succeeded but returned no token.")

        # Databricks Apps inject PG* variables and expect the app's own OAuth
        # token to be used as the password.
        auth_headers = sdk.config.authenticate()
        if auth_headers and "Authorization" in auth_headers:
            return auth_headers["Authorization"].replace("Bearer ", "")
        if getattr(sdk.config, "token", None):
            return sdk.config.token
    except Exception as e:
        logger.error("Failed to fetch Lakebase token: %s: %s", type(e).__name__, e)

    return None


def get_database_url() -> str:
    """Resolve the connection URL, falling back to SQLite when Lakebase isn't configured."""
    global _lakebase_endpoint

    if settings.DATABASE_URL:
        logger.warning("DATABASE_URL is set explicitly; using it as-is.")
        return settings.DATABASE_URL

    pg_host = os.environ.get("PGHOST")
    pg_user = os.environ.get("PGUSER")
    pg_name = os.environ.get("PGDATABASE")
    pg_port = os.environ.get("PGPORT", "5432")

    host = pg_host or settings.DATABASE_HOST
    user = pg_user or settings.DATABASE_USER or "atlas_app"
    name = pg_name or settings.DATABASE_NAME
    port = pg_port or settings.DATABASE_PORT
    password = settings.DATABASE_PASSWORD
    db_id = None

    if host and user and name:
        if pg_host:
            logger.info("Using Databricks Apps injected PG variables for Lakebase.")
            password = get_lakebase_token()
        elif settings.DATABASE_PASSWORD:
            logger.info("Using injected DATABASE_PASSWORD (resource binding).")
            password = settings.DATABASE_PASSWORD
            user = settings.DATABASE_USER
            name = settings.DATABASE_NAME
        else:
            is_databricks = bool(
                os.environ.get("DATABRICKS_RUNTIME_VERSION")
                or os.environ.get("DATABRICKS_HOST")
                or os.environ.get("DATABRICKS_INSTANCE_POOL_ID")
                or os.path.exists("/databricks")
                or "database.cloud.databricks.com" in (host or "")
            )
            if is_databricks:
                user, db_id, password = _resolve_lakebase_project(user)

        if password:
            safe_user = quote_plus(user)
            safe_password = quote_plus(password)
            # Autoscaling Lakebase addresses the database by its ID, not its name.
            db_name_to_use = db_id or name

            logger.info(
                "Lakebase connection: host=%s user=%s database=%s", host, user, db_name_to_use
            )
            return (
                f"postgresql://{safe_user}:{safe_password}@{host}:{port}/"
                f"{db_name_to_use}?sslmode=require"
            )

        logger.warning("No Lakebase credential available. Falling back to SQLite.")

    return _sqlite_url()


def _resolve_lakebase_project(user: str):
    """Discover the Lakebase project, database ID, and an initial token."""
    global _lakebase_endpoint

    try:
        from databricks.sdk import WorkspaceClient

        _ensure_databricks_host_scheme()
        sdk = WorkspaceClient()

        user = sdk.current_user.me().user_name
        logger.info("Using Databricks workspace user for Lakebase: %s", user)

        projects = sdk.api_client.do("GET", "/api/2.0/postgres/projects").get("projects", [])
        target = settings.DATABASE_INSTANCE_NAME
        matched = None

        if target:
            matched = next((p for p in projects if p.get("name", "").endswith(target)), None)
        elif projects:
            matched = projects[0]
            target = matched.get("name")
            logger.warning(
                "DATABASE_INSTANCE_NAME not set; auto-discovered project %s.", target
            )

        if not (matched and target):
            logger.error("No Lakebase project found to connect to.")
            return user, None, None

        _lakebase_endpoint = f"projects/{target}/branches/production/endpoints/primary"

        db_id = None
        try:
            databases = sdk.api_client.do(
                "GET", f"/api/2.0/postgres/projects/{target}/branches/production/databases"
            ).get("databases", [])
            if databases:
                db_id = databases[0].get("name", "").split("/")[-1]
                logger.info("Auto-discovered Lakebase database ID: %s", db_id)
        except Exception as e:
            logger.warning("Could not auto-discover database ID: %s", e)

        return user, db_id, get_lakebase_token(_lakebase_endpoint)
    except Exception as e:
        logger.error("Failed to resolve Lakebase project: %s: %s", type(e).__name__, e)
        return user, None, None


def _sqlite_url() -> str:
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    if os.environ.get("DATABRICKS_RUNTIME_VERSION") or os.environ.get("DATABRICKS_HOST"):
        persistent_dir = "/tmp/sentinel_hub_data"
        for env_var in ("USER", "DATABRICKS_USER", "OWNER"):
            db_user = os.environ.get(env_var)
            if db_user:
                persistent_dir = f"/Workspace/Users/{db_user}/sentinel_hub_data"
                break
        try:
            os.makedirs(persistent_dir, exist_ok=True)
            db_path = os.path.join(persistent_dir, "sentinel.db")
            logger.info("Using persistent SQLite database at %s", db_path)
            return f"sqlite:///{db_path}"
        except Exception as e:
            logger.warning("Could not create %s (%s); using the local file.", persistent_dir, e)

    return f"sqlite:///{os.path.join(base_dir, 'sentinel.db')}"


def get_engine():
    """Get or create the engine (lazily, so importing this module is cheap)."""
    global _engine
    if _engine is not None:
        return _engine

    database_url = get_database_url()

    if database_url.startswith("sqlite"):
        is_memory = ":memory:" in database_url
        _engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool if is_memory else NullPool,
            echo=False,
        )
        return _engine

    schema = settings.DB_SCHEMA
    _engine = create_engine(
        database_url,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        # Retire connections before Lakebase drops them for idleness.
        pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
        connect_args={
            # Part of the connection itself, so a rolled-back transaction can't
            # silently leave queries resolving against `public`.
            "options": f"-csearch_path={schema},public",
            # Notice a half-open connection in ~40s instead of hanging on it.
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
            "connect_timeout": 10,
        },
        echo=False,
    )

    @event.listens_for(_engine, "do_connect")
    def provide_fresh_token(dialect, conn_rec, cargs, cparams):
        """Swap in a freshly minted token for each new physical connection.

        Without this, the pool hands out connections authenticated with a token
        captured at startup, and everything works until it abruptly doesn't.
        """
        if not _lakebase_endpoint and not os.environ.get("PGHOST"):
            return None

        token = get_lakebase_token()
        if token:
            cparams["password"] = token
        else:
            logger.warning("Could not refresh Lakebase token; using the existing credential.")
        return None

    @event.listens_for(_engine, "connect")
    def ensure_schema(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}";')
            dbapi_connection.commit()
        except Exception as e:
            # Not fatal: the schema usually already exists and the app may be
            # connecting as a role without CREATE.
            logger.warning("Could not ensure schema %s exists: %s", schema, e)
        finally:
            cursor.close()

    logger.info(
        "Postgres engine configured (schema=%s, pool_recycle=%ss).",
        schema,
        settings.DB_POOL_RECYCLE_SECONDS,
    )
    return _engine


def get_session_local():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency."""
    db = get_session_local()()
    try:
        yield db
    finally:
        db.close()


def get_lakebase_session() -> Session:
    """Session for workers and background tasks. The caller must close it.

    Long-running work should take one of these, use it, and close it promptly
    rather than holding it open across the whole task — see the note in
    backend/AGENTS.md about short-lived sessions.
    """
    return get_session_local()()
