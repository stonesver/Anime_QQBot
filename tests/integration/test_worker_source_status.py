from __future__ import annotations

import os
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from anime_qqbot.entrypoints import cli
from anime_qqbot.persistence.models.catalog import SourceSyncState


@pytest.fixture
async def session_factory():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.exec_driver_sql("TRUNCATE TABLE source_sync_states")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def test_successful_bangumi_cycle_persists_source_success(
    session_factory,
    monkeypatch,
) -> None:
    now = datetime(2026, 7, 30, 1, 0, tzinfo=UTC)

    async def discover(_components, *, limit: int) -> int:
        assert limit == 100
        return 3

    async def ingest(_components, *, limit: int) -> None:
        assert limit == 100

    monkeypatch.setattr(cli, "_discover_calendar_subjects", discover)
    monkeypatch.setattr(cli, "_ingest_known_subjects", ingest)

    discovered = await cli._sync_bangumi_catalog(
        SimpleNamespace(sessions=session_factory),
        now=now,
        limit=100,
    )

    async with session_factory() as session:
        state = await session.get(SourceSyncState, "bangumi")
    assert discovered == 3
    assert state is not None
    assert state.last_success_at == now
    assert state.last_failure_at is None
    assert state.last_error is None


async def test_failed_bangumi_cycle_persists_source_failure(
    session_factory,
    monkeypatch,
) -> None:
    now = datetime(2026, 7, 30, 2, 0, tzinfo=UTC)

    async def discover(_components, *, limit: int) -> int:
        raise RuntimeError("calendar unavailable")

    monkeypatch.setattr(cli, "_discover_calendar_subjects", discover)

    with pytest.raises(RuntimeError, match="calendar unavailable"):
        await cli._sync_bangumi_catalog(
            SimpleNamespace(sessions=session_factory),
            now=now,
            limit=100,
        )

    async with session_factory() as session:
        state = await session.get(SourceSyncState, "bangumi")
    assert state is not None
    assert state.last_success_at is None
    assert state.last_failure_at == now
    assert state.last_error == "calendar unavailable"
