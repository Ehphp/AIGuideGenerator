"""Async SQLAlchemy engine + session factory + declarative Base."""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an AsyncSession."""
    async with SessionLocal() as session:
        yield session


async def create_all() -> None:
    """Create tables. Used at startup until Alembic is introduced (Phase 7)."""
    # Import models so they register on Base.metadata.
    from app.models import job as _job  # noqa: F401
    from app.models import session as _session  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
