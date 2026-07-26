"""Integration tests for the internal Anime read repository."""

from __future__ import annotations

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from anime_qqbot.catalog.repository_v2 import (
    CatalogReadRepository,
    CatalogWriteRepository,
)


def _engine():
    return create_async_engine(os.environ["TEST_DATABASE_URL"])


async def _reset_schema(engine) -> None:
    async with engine.begin() as conn:
        # Wipe data only — legacy subscriptions FKs into anime_subjects
        # so we cannot drop_all; tests run against the migrated schema.
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


def _write(factory) -> CatalogWriteRepository:
    return CatalogWriteRepository(factory)


def _read(factory) -> CatalogReadRepository:
    return CatalogReadRepository(factory)


async def _seed_basic(factory):
    write = _write(factory)
    bangumi = await write.upsert_external_entry(provider="bangumi", external_id="100")
    anime = await write.create_anime(display_title="Title A")
    await write.add_source_link(
        anime_id=anime.id,
        external_entry_id=bangumi.id,
        status="confirmed",
        evidence_type="manual",
        confidence=1.0,
        method="seed",
    )
    return {"bangumi": bangumi, "anime": anime}


async def test_find_anime_by_internal_id(session_factory) -> None:
    seeded = await _seed_basic(session_factory)
    reader = _read(session_factory)

    anime = await reader.find_anime_by_id(seeded["anime"].id)

    assert anime is not None
    assert anime.id == seeded["anime"].id


async def test_find_anime_by_external_identity(session_factory) -> None:
    seeded = await _seed_basic(session_factory)
    reader = _read(session_factory)

    anime = await reader.find_anime_by_external("bangumi", "100")

    assert anime is not None
    assert anime.id == seeded["anime"].id


async def test_search_by_title_finds_match(session_factory) -> None:
    seeded = await _seed_basic(session_factory)
    reader = _read(session_factory)

    results = await reader.search_anime_by_title("Title A")

    assert len(results) == 1
    assert results[0].id == seeded["anime"].id


async def test_search_by_season_finds_match(session_factory) -> None:
    seeded = await _seed_basic(session_factory)
    reader = _read(session_factory)

    results = await reader.search_anime_by_season(year=2026, name="夏")

    assert len(results) == 1
    assert results[0].id == seeded["anime"].id


async def test_disabled_anime_is_excluded_from_search(session_factory) -> None:
    seeded = await _seed_basic(session_factory)
    await _write(session_factory).disable_anime(seeded["anime"].id)

    results = await _read(session_factory).search_anime_by_title("Title A")

    assert results == []


async def test_disabled_external_entry_excludes_match(session_factory) -> None:
    seeded = await _seed_basic(session_factory)
    await _write(session_factory).disable_external_entry(seeded["bangumi"].id)

    anime = await _read(session_factory).find_anime_by_external("bangumi", "100")

    assert anime is None


async def test_nsfw_true_anime_excluded_from_search(session_factory) -> None:
    seeded = await _seed_basic(session_factory)
    await _write(session_factory).mark_nsfw(seeded["anime"].id, flag="true")

    results = await _read(session_factory).search_anime_by_title("Title A")

    assert results == []


async def test_nsfw_unknown_anime_visible_in_search(session_factory) -> None:
    seeded = await _seed_basic(session_factory)
    await _write(session_factory).mark_nsfw(seeded["anime"].id, flag="unknown")

    results = await _read(session_factory).search_anime_by_title("Title A")

    assert len(results) == 1
    assert results[0].id == seeded["anime"].id
