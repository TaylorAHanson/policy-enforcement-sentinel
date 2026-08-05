"""Shared test fixtures.

Two things matter here beyond the usual boilerplate:

1. Tests run against an **in-memory** SQLite database. Before this existed, the
   suite imported ``app.main``, which ran ``create_all`` against the real
   ``backend/sentinel.db`` and then wrote to it — tests polluted the developer's
   local data and leaked state into each other.

2. The ``client`` fixture overrides ``get_db`` *and* neutralises ``close()`` on
   the session it hands out. Service code deliberately opens short-lived
   sessions and closes them (see ``sentinel_service``); without the guard the
   first ``close()`` would end the test's transaction and every later assertion
   would query a dead session.
"""
import os
import sys
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Make ``app`` importable when pytest is invoked from the repo root as well as
# from ``backend/``.
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Force the dev/test defaults before any app module reads settings.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.db.base import Base  # noqa: E402
import app.db  # noqa: F401,E402  (registers every model on Base.metadata)

TEST_DB_URL = "sqlite:///:memory:"


def pytest_addoption(parser):
    parser.addoption(
        "--mode",
        action="store",
        default="mock",
        help="Test mode: 'mock' (default, no external calls) or 'real'.",
    )


@pytest.fixture(scope="session")
def test_mode(request) -> str:
    return request.config.getoption("--mode")


@pytest.fixture(scope="session")
def db_engine():
    engine = create_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_session(db_engine) -> Iterator[Session]:
    """A session wrapped in a transaction that is rolled back after each test."""
    connection = db_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


class _NonClosingSession:
    """Proxy that forwards everything to the real session but swallows close().

    Application code opens and closes its own short-lived sessions. In a test
    those all resolve to the single transactional session, so an honest
    ``close()`` would tear down the test's transaction partway through.
    """

    def __init__(self, session: Session):
        self._session = session

    def __getattr__(self, name):
        if name == "close":
            return lambda: None
        return getattr(self._session, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


@pytest.fixture(scope="function")
def app_db(db_session, monkeypatch):
    """Point every app-side session factory at the test session."""
    proxy = _NonClosingSession(db_session)

    from app.db import session as session_module

    monkeypatch.setattr(session_module, "get_lakebase_session", lambda: proxy)
    monkeypatch.setattr(session_module, "SessionLocal", lambda: proxy, raising=False)
    return proxy


@pytest.fixture(scope="function")
def client(db_session, app_db):
    """FastAPI TestClient with the database dependency overridden."""
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import app

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def policies_dir() -> Path:
    """Path to the real Rego policy directory."""
    return BACKEND_DIR / "policies"


@pytest.fixture
def opa_binary() -> str:
    """Resolve an ``opa`` binary, or skip the test when one isn't available."""
    import shutil

    from app.core.config import settings

    candidate = settings.OPA_BINARY or shutil.which("opa")
    if not candidate or not os.path.exists(candidate):
        pytest.skip("opa binary not available")
    return candidate
