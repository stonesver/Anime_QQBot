"""Unit tests for the Bangumi catalog sync (Task 5)."""

from __future__ import annotations

import os
from datetime import date
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from anime_qqbot.catalog.bangumi_sync import BangumiCatalogSync
from anime_qqbot.catalog.models import AnimeDetail
from anime_qqbot.catalog.ports import BangumiProvider
from anime_qqbot.catalog.repository_v2 import (
    CatalogReadRepository,
    CatalogWriteRepository,
)


class _StubBangumi(BangumiProvider):
    def __init__(self, detail: AnimeDetail | None) -> None:
        self._detail = detail
        self.calls = 0

    async def search(self, query: str) -> list[Any]:
        return []

    async def get_detail(self, subject_id: int) -> AnimeDetail | None:
        self.calls += 1
        return self._detail

    async def calendar(self) -> list[Any]:
        return []

    async def episodes(self, subject_id: int) -> list[Any]:
        return []


def _engine():
    return create_async_engine(os.environ["TEST_DATABASE_URL"])


async def _reset(engine) -> None:
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "TRUNCATE TABLE source_snapshots, anime_source_links, "
            "anime_titles, airing_occurrences, external_entries, animes, "
            "source_sync_states RESTART IDENTITY CASCADE"
        )


@pytest.fixture
async def session_factory():
    engine = _engine()
    await _reset(engine)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


def _detail() -> AnimeDetail:
    return AnimeDetail(
        subject_id=42,
        title_cn="夏日物语",
        title_jp="夏物語",
        air_date=date(2026, 7, 1),
        summary="概要",
        score=8.2,
        total_episodes=12,
        nsfw=False,
    )


async def test_first_contact_creates_internal_anime_and_confirmed_link(
    session_factory,
) -> None:
    bangumi = _StubBangumi(_detail())
    write = CatalogWriteRepository(session_factory)
    read = CatalogReadRepository(session_factory)
    sync = BangumiCatalogSync(bangumi, write)

    result = await sync.sync_subject(42)

    assert result.is_new_anime is True
    assert bangumi.calls == 1
    anime = await read.find_anime_by_id(result.anime_id)
    assert anime is not None
    assert anime.display_title == "夏日物语"


async def test_second_contact_does_not_create_new_anime(session_factory) -> None:
    bangumi = _StubBangumi(_detail())
    write = CatalogWriteRepository(session_factory)
    sync = BangumiCatalogSync(bangumi, write)

    first = await sync.sync_subject(42)
    second = await sync.sync_subject(42)

    assert first.is_new_anime is True
    assert second.is_new_anime is False
    assert second.anime_id == first.anime_id
    assert bangumi.calls == 2


async def test_unknown_subject_raises(session_factory) -> None:
    bangumi = _StubBangumi(None)
    write = CatalogWriteRepository(session_factory)
    sync = BangumiCatalogSync(bangumi, write)

    with pytest.raises(LookupError):
        await sync.sync_subject(999)


async def test_nsfw_true_is_recorded_as_such(session_factory) -> None:
    detail = AnimeDetail(
        subject_id=77,
        title_cn=None,
        title_jp="Adult",
        air_date=None,
        nsfw=True,
    )
    bangumi = _StubBangumi(detail)
    write = CatalogWriteRepository(session_factory)
    read = CatalogReadRepository(session_factory)
    sync = BangumiCatalogSync(bangumi, write)

    result = await sync.sync_subject(77)

    row = await read.find_anime_by_id(result.anime_id)
    assert row is not None
    assert row.nsfw_flag == "true"


async def test_snapshot_payload_includes_normalized_fields(session_factory) -> None:
    bangumi = _StubBangumi(_detail())
    write = CatalogWriteRepository(session_factory)
    sync = BangumiCatalogSync(bangumi, write)

    result = await sync.sync_subject(42)

    snap = await write.current_snapshot(result.external_entry.id)

    assert snap is not None
    payload = snap.payload
    assert payload["title_cn"] == "夏日物语"
    assert payload["title_jp"] == "夏物語"
    assert payload["score"] == 8.2
    assert payload["air_date"] == "2026-07-01"


async def test_snapshot_versions_increment(session_factory) -> None:
    bangumi = _StubBangumi(_detail())
    write = CatalogWriteRepository(session_factory)
    sync = BangumiCatalogSync(bangumi, write)

    await sync.sync_subject(42)
    await sync.sync_subject(42)

    entry = await write.upsert_external_entry(provider="bangumi", external_id="42")
    latest = await write.current_snapshot(entry.id)

    assert latest is not None
    assert latest.version == 2


async def test_old_anime_subjects_table_is_not_touched(session_factory) -> None:
    """First sync must not write to v0.1 cache tables; later read-only
    fallbacks depend on them staying intact."""

    bangumi = _StubBangumi(_detail())
    write = CatalogWriteRepository(session_factory)
    sync = BangumiCatalogSync(bangumi, write)

    await sync.sync_subject(42)

    engine = _engine()
    async with engine.connect() as conn:
        from sqlalchemy import text

        rows = (await conn.execute(text("SELECT COUNT(*) FROM anime_subjects"))).scalar()
    await engine.dispose()
    assert rows == 0
