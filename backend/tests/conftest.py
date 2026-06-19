"""Pytest configuration and shared fixtures for AutoFormFiller backend tests.

Provides:
  - db_session:   Synchronous SQLAlchemy session bound to the live test DB
                  (uses DATABASE_SYNC_URL from environment or a sensible default)
  - rls_context:  Sets a dummy Postgres RLS session variable so RLS policies
                  don't block test inserts
  - celery_app:   The Celery application in ALWAYS_EAGER mode so tasks run
                  synchronously in the test process
  - async_db_session: AsyncSession variant for async tests
"""

from __future__ import annotations

import os
import pytest
import pytest_asyncio

# ── Ensure PYTHONPATH includes ai_services ─────────────────────────────────────
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "ai_services"))

# ── Default to test DB if nothing set ────────────────────────────────────────────
os.environ.setdefault(
    "DATABASE_SYNC_URL",
    "postgresql://autoform:autoform_secret@localhost:5432/autoformfiller",
)
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://autoform:autoform_secret@localhost:5432/autoformfiller",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("MASTER_ENCRYPTION_KEY", "dGVzdC1tYXN0ZXIta2V5LTMyLWJ5dGVzLWxvbmc=")
os.environ.setdefault("MINIO_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin_secret_change_in_prod")
os.environ.setdefault("APP_ENV", "test")

# ──────────────────────────────────────────────────────────────────────────────
# Synchronous DB session (most unit/integration tests)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def db_session():
    """Return a synchronous SQLAlchemy session for the test database.

    Each test runs inside a savepoint (nested transaction) that is rolled back
    after the test completes, keeping the DB clean.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from app.core.config import settings

    sync_url = getattr(settings, "DATABASE_SYNC_URL", os.environ["DATABASE_SYNC_URL"])
    engine = create_engine(sync_url, echo=False)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    connection = engine.connect()
    transaction = connection.begin()

    # Create a session bound to this connection so savepoints work
    session = SessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


# ──────────────────────────────────────────────────────────────────────────────
# RLS context — set a dummy app.current_user_id Postgres variable
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def rls_context(db_session):
    """Set the Postgres session variable used by RLS policies."""
    from sqlalchemy import text
    try:
        db_session.execute(
            text("SET LOCAL app.current_user_id = 'test-user-id'")
        )
    except Exception:
        # Some DB versions or setups may not support this — skip silently
        pass
    yield


# ──────────────────────────────────────────────────────────────────────────────
# Celery in ALWAYS_EAGER mode
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def celery_app():
    """Return the configured Celery app in always-eager mode."""
    from app.celery_app import celery_app as app

    app.conf.update(
        task_always_eager=True,
        task_eager_propagates=True,
    )
    return app


# ──────────────────────────────────────────────────────────────────────────────
# Async DB session (for async tests)
# ──────────────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="function")
async def async_db_session():
    """Async SQLAlchemy session for async test functions."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from app.core.config import settings

    async_url = getattr(settings, "DATABASE_URL", os.environ["DATABASE_URL"])
    engine = create_async_engine(async_url, echo=False)
    AsyncSession_ = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSession_() as session:
        async with session.begin():
            yield session
            await session.rollback()

    await engine.dispose()
