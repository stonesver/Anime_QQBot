from __future__ import annotations

import os
from datetime import UTC, date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from anime_qqbot.persistence.models.catalog import (
    AiringOccurrenceRow,
    Anime,
    AnimeSourceLink,
    ExternalEntry,
    SourceSnapshot,
)
from anime_qqbot.presentation.assembler import CardDataAssembler


@pytest.fixture
async def sessions() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    async with engine.begin() as connection:
        await connection.exec_driver_sql(
            "TRUNCATE TABLE source_snapshots, anime_source_links, "
            "airing_occurrences, external_entries, animes RESTART IDENTITY CASCADE"
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def test_assembles_latest_confirmed_local_projection(sessions) -> None:
    now = datetime(2026, 7, 29, 8, tzinfo=UTC)
    anime_id = uuid4()
    bangumi_id = uuid4()
    anilist_id = uuid4()
    mikan_id = uuid4()
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
        entries = [
            ExternalEntry(
                id=bangumi_id,
                provider="bangumi",
                external_id="42",
                disabled=False,
                created_at=now,
                updated_at=now,
            ),
            ExternalEntry(
                id=anilist_id,
                provider="anilist",
                external_id="84",
                disabled=False,
                created_at=now,
                updated_at=now,
            ),
            ExternalEntry(
                id=mikan_id,
                provider="mikan",
                external_id="21",
                disabled=False,
                created_at=now,
                updated_at=now,
            ),
        ]
        session.add_all(entries)
        for entry in entries:
            session.add(
                AnimeSourceLink(
                    id=uuid4(),
                    anime_id=anime_id,
                    external_entry_id=entry.id,
                    status="confirmed",
                    evidence_type="manual",
                    confidence=1.0,
                    method="fixture",
                    created_at=now,
                )
            )
        session.add_all(
            [
                SourceSnapshot(
                    id=uuid4(),
                    external_entry_id=bangumi_id,
                    version=1,
                    payload={"score": 7.0, "total_episodes": 10},
                    source_time=now,
                    fetched_at=now,
                ),
                SourceSnapshot(
                    id=uuid4(),
                    external_entry_id=bangumi_id,
                    version=2,
                    payload={
                        "title_jp": "夏物語",
                        "score": 8.2,
                        "total_episodes": 12,
                        "release_year": 2026,
                        "season_name": "夏",
                    },
                    source_time=now,
                    fetched_at=now,
                ),
                SourceSnapshot(
                    id=uuid4(),
                    external_entry_id=anilist_id,
                    version=1,
                    payload={"title_romaji": "Natsu Monogatari", "media_format": "TV"},
                    source_time=now,
                    fetched_at=now,
                ),
            ]
        )
        session.add(
            AiringOccurrenceRow(
                id=uuid4(),
                anime_id=anime_id,
                source_entry_id=anilist_id,
                episode_label="04",
                air_date=date(2026, 7, 30),
                air_at=datetime(2026, 7, 30, 10, tzinfo=UTC),
                precision="exact",
                source_event_key="fixture:04",
                updated_at=now,
            )
        )

    data = await CardDataAssembler(sessions).assemble(
        anime_id,
        timezone=ZoneInfo("Asia/Shanghai"),
        now=now,
    )

    assert data is not None
    assert data.display_title == "夏日物语"
    assert data.title_jp == "Natsu Monogatari"
    assert data.bangumi_score == 8.2
    assert data.total_episodes == 12
    assert data.media_format == "TV"
    assert data.sources == ("bangumi", "anilist", "mikan")
    assert data.next_airing is not None
    assert data.next_airing.episode_label == "04"


async def test_blocked_anime_never_enters_card_data(sessions) -> None:
    now = datetime(2026, 7, 29, 8, tzinfo=UTC)
    anime_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            Anime(
                id=anime_id,
                display_title="blocked",
                nsfw_flag="true",
                disabled=False,
                created_at=now,
                updated_at=now,
            )
        )

    data = await CardDataAssembler(sessions).assemble(
        anime_id,
        timezone=ZoneInfo("Asia/Shanghai"),
        now=now,
    )

    assert data is None
