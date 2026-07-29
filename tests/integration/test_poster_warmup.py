from __future__ import annotations

import os
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from anime_qqbot.persistence.models.catalog import (
    Anime,
    AnimeSourceLink,
    ExternalEntry,
    SourceSnapshot,
)
from anime_qqbot.presentation.poster_cache import PosterCache
from anime_qqbot.presentation.poster_warmup import PosterWarmupService


@pytest.fixture
async def sessions() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    async with engine.begin() as connection:
        await connection.exec_driver_sql(
            "TRUNCATE TABLE source_snapshots, anime_source_links, "
            "external_entries, animes RESTART IDENTITY CASCADE"
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


def poster_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (400, 600), "#365FC7").save(output, format="PNG")
    return output.getvalue()


async def seed_candidates(sessions) -> object:
    now = datetime(2026, 7, 29, 8, tzinfo=UTC)
    anime_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            Anime(
                id=anime_id,
                display_title="夏日物语",
                nsfw_flag="unknown",
                disabled=False,
                created_at=now,
                updated_at=now,
            )
        )
        for provider in ("bangumi", "anilist"):
            entry_id = uuid4()
            session.add(
                ExternalEntry(
                    id=entry_id,
                    provider=provider,
                    external_id=provider,
                    disabled=False,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                AnimeSourceLink(
                    id=uuid4(),
                    anime_id=anime_id,
                    external_entry_id=entry_id,
                    status="confirmed",
                    evidence_type="manual",
                    confidence=1.0,
                    method="fixture",
                    created_at=now,
                )
            )
            session.add(
                SourceSnapshot(
                    id=uuid4(),
                    external_entry_id=entry_id,
                    version=1,
                    payload={"image_url": f"https://example.com/{provider}.png"},
                    source_time=now,
                    fetched_at=now,
                )
            )
    return anime_id


async def test_uses_bangumi_first_and_anilist_as_validation_fallback(
    sessions,
    tmp_path: Path,
) -> None:
    anime_id = await seed_candidates(sessions)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        content = b"bad image" if "bangumi" in request.url.path else poster_bytes()
        return httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=content,
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cache = PosterCache(tmp_path, client=client)

    summary = await PosterWarmupService(sessions, cache).run_once(limit=5)

    assert summary.stored == 1
    assert summary.failed == 0
    assert calls == ["/bangumi.png", "/anilist.png"]
    assert cache.find_local_poster(anime_id) is not None
    await client.aclose()
