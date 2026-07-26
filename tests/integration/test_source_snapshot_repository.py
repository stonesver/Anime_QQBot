"""Integration tests for the source snapshot repository."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from anime_qqbot.catalog.repository_v2 import CatalogWriteRepository


def _engine():
    return create_async_engine(os.environ["TEST_DATABASE_URL"])


async def _reset_schema(engine) -> None:
    async with engine.begin() as conn:
        # Wipe data only — the legacy subscriptions table has FKs into
        # anime_subjects so we cannot drop_all; tests must operate against
        # the migrated schema and keep it intact.
        await conn.exec_driver_sql(
            "TRUNCATE TABLE source_snapshots, anime_source_links, "
            "anime_titles, airing_occurrences, external_entries, animes, "
            "source_sync_states RESTART IDENTITY CASCADE"
        )


@pytest.fixture
async def session_factory():
    engine = _engine()
    await _reset_schema(engine)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


def _repo(factory) -> CatalogWriteRepository:
    return CatalogWriteRepository(factory)


async def test_upsert_external_entry_is_idempotent(session_factory) -> None:
    repo = _repo(session_factory)

    first = await repo.upsert_external_entry(provider="bangumi", external_id="42")
    second = await repo.upsert_external_entry(
        provider="bangumi",
        external_id="42",
        url="https://bgm.tv/subject/42",
    )

    assert first.id == second.id
    assert second.url == "https://bgm.tv/subject/42"


async def test_different_providers_get_different_entries(session_factory) -> None:
    repo = _repo(session_factory)

    bangumi = await repo.upsert_external_entry(provider="bangumi", external_id="42")
    anilist = await repo.upsert_external_entry(provider="anilist", external_id="42")

    assert bangumi.id != anilist.id


async def test_append_snapshot_is_idempotent_on_version(session_factory) -> None:
    repo = _repo(session_factory)
    entry = await repo.upsert_external_entry(provider="bangumi", external_id="100")

    ts = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
    first = await repo.append_snapshot(
        entry_id=entry.id,
        version=1,
        payload={"title": "Same"},
        source_time=ts,
        fetched_at=ts,
    )
    second = await repo.append_snapshot(
        entry_id=entry.id,
        version=1,
        payload={"title": "Same"},
        source_time=ts,
        fetched_at=ts,
    )

    assert first.id == second.id


async def test_payload_change_creates_new_snapshot(session_factory) -> None:
    repo = _repo(session_factory)
    entry = await repo.upsert_external_entry(provider="bangumi", external_id="100")

    ts = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
    snap = await repo.append_snapshot(
        entry_id=entry.id,
        version=1,
        payload={"title": "Same"},
        source_time=ts,
        fetched_at=ts,
    )
    snap2 = await repo.append_snapshot(
        entry_id=entry.id,
        version=2,
        payload={"title": "Changed"},
        source_time=ts,
        fetched_at=datetime(2026, 7, 15, 11, 0, tzinfo=UTC),
    )

    assert snap.id != snap2.id
    assert snap2.version == 2


async def test_latest_snapshot_pointer(session_factory) -> None:
    repo = _repo(session_factory)
    entry = await repo.upsert_external_entry(provider="bangumi", external_id="100")

    ts = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
    await repo.append_snapshot(
        entry_id=entry.id,
        version=1,
        payload={"v": 1},
        source_time=ts,
        fetched_at=ts,
    )
    latest = await repo.append_snapshot(
        entry_id=entry.id,
        version=2,
        payload={"v": 2},
        source_time=ts,
        fetched_at=datetime(2026, 7, 15, 12, 0, tzinfo=UTC),
    )

    current = await repo.current_snapshot(entry.id)

    assert current is not None
    assert current.id == latest.id
    assert current.payload == {"v": 2}


async def test_concurrent_upserts_resolve_to_one_entry(session_factory) -> None:
    repo = _repo(session_factory)

    async def _do() -> uuid.UUID:
        entry = await repo.upsert_external_entry(provider="bangumi", external_id="999")
        return entry.id

    ids = await asyncio.gather(*[_do() for _ in range(5)])

    assert len(set(ids)) == 1
