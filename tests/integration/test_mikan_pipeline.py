from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from anime_qqbot.entrypoints.cli import _register_mikan_link
from anime_qqbot.notifications.outbox import OutboxRepository
from anime_qqbot.persistence.models.catalog import Anime, AnimeSourceLink, ExternalEntry
from anime_qqbot.persistence.models.identity import ChatGroup
from anime_qqbot.persistence.models.notifications_v2 import NotificationJob
from anime_qqbot.persistence.models.resources import MikanFeedState, ReleaseBatch, ResourceRelease
from anime_qqbot.persistence.models.subscriptions_v2 import (
    FollowSubscription,
    SubscriptionResourceFilter,
)
from anime_qqbot.resources.adapters.mikan import MikanFeedResult, MikanItem
from anime_qqbot.resources.module import MikanReleasePipeline

RSS_URL = "https://mikanani.me/RSS/Bangumi?bangumiId=123"
NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


class FakeMikanClient:
    def __init__(self, results: list[MikanFeedResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, str | None, str | None]] = []

    async def fetch_feed(
        self,
        rss_url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> MikanFeedResult:
        self.calls.append((rss_url, etag, last_modified))
        return self.results.pop(0)


@pytest.fixture
async def sessions() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "TRUNCATE TABLE delivery_attempts, notification_jobs, "
            "release_batch_items, release_batches, resource_releases, mikan_feed_states, "
            "subscription_resource_filters, follow_subscriptions, "
            "source_snapshots, anime_source_links, anime_titles, airing_occurrences, "
            "external_entries, animes, source_sync_states, chat_groups, group_memberships "
            "RESTART IDENTITY CASCADE"
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _seed_follow(
    sessions: async_sessionmaker[AsyncSession],
    *,
    user_id: str,
    group_id,
    anime_id,
    language: str | None = None,
) -> None:
    subscription_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            FollowSubscription(
                id=subscription_id,
                chat_group_id=group_id,
                external_user_id=user_id,
                anime_id=anime_id,
                notify_airing=True,
                notify_resource=True,
                created_at=NOW,
            )
        )
        if language is not None:
            session.add(
                SubscriptionResourceFilter(
                    id=uuid4(),
                    subscription_id=subscription_id,
                    language=language,
                    subtitle_groups=[],
                    resolutions=[],
                    updated_at=NOW,
                )
            )


async def _seed_target(sessions: async_sessionmaker[AsyncSession]) -> tuple[object, object]:
    anime_id = uuid4()
    entry_id = uuid4()
    group_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            Anime(
                id=anime_id,
                nsfw_flag="false",
                disabled=False,
                display_title="Example Anime",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            ExternalEntry(
                id=entry_id,
                provider="mikan",
                external_id="123",
                url=RSS_URL,
                disabled=False,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            ChatGroup(
                id=group_id,
                platform="qq",
                external_group_id="42",
                unified_msg_origin="umo:42",
                timezone="Asia/Shanghai",
                enabled=True,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            AnimeSourceLink(
                id=uuid4(),
                anime_id=anime_id,
                external_entry_id=entry_id,
                status="confirmed",
                evidence_type="mikan_bangumi_link",
                confidence=1.0,
                method="fixture",
                created_at=NOW,
            )
        )
    await _seed_follow(sessions, user_id="u-chs", group_id=group_id, anime_id=anime_id)
    await _seed_follow(
        sessions,
        user_id="u-cht",
        group_id=group_id,
        anime_id=anime_id,
        language="cht",
    )
    return anime_id, group_id


def _feed(*, not_modified: bool = False) -> MikanFeedResult:
    if not_modified:
        return MikanFeedResult(
            items=(),
            etag='"v1"',
            last_modified="Tue, 28 Jul 2026 12:00:00 GMT",
            not_modified=True,
        )
    return MikanFeedResult(
        items=(
            MikanItem(
                guid="release-1",
                title="[Group A] Example Anime [01][1080p][简日]",
                pub_date=NOW,
                page_url="https://mikanani.me/Home/Episode/release-1",
            ),
        ),
        etag='"v1"',
        last_modified="Tue, 28 Jul 2026 12:00:00 GMT",
    )


async def test_poll_deduplicates_feed_and_persists_release_batch(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_target(sessions)
    client = FakeMikanClient([_feed(), _feed(not_modified=True)])
    pipeline = MikanReleasePipeline(
        sessions=sessions,
        client=client,
        outbox=OutboxRepository(sessions),
    )

    first = await pipeline.run_once(NOW)
    second = await pipeline.run_once(NOW + timedelta(minutes=5))

    assert first.feeds_polled == 1
    assert first.releases_created == 1
    assert second.releases_created == 0
    assert client.calls == [
        (RSS_URL, None, None),
        (RSS_URL, '"v1"', "Tue, 28 Jul 2026 12:00:00 GMT"),
    ]
    async with sessions() as session:
        release_count = await session.scalar(select(func.count()).select_from(ResourceRelease))
        batch_count = await session.scalar(select(func.count()).select_from(ReleaseBatch))
        state = await session.get(MikanFeedState, "mikan:123")
    assert release_count == 1
    assert batch_count == 1
    assert state is not None
    assert state.etag == '"v1"'


async def test_restart_closes_batch_and_enqueues_filtered_group_job(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    _, group_id = await _seed_target(sessions)
    first = MikanReleasePipeline(
        sessions=sessions,
        client=FakeMikanClient([_feed()]),
        outbox=OutboxRepository(sessions),
    )
    await first.run_once(NOW)

    restarted = MikanReleasePipeline(
        sessions=sessions,
        client=FakeMikanClient([_feed(not_modified=True)]),
        outbox=OutboxRepository(sessions),
    )
    result = await restarted.run_once(NOW + timedelta(minutes=10))

    assert result.batches_closed == 1
    async with sessions() as session:
        batch = (await session.execute(select(ReleaseBatch))).scalar_one()
        job = (await session.execute(select(NotificationJob))).scalar_one()
    assert batch.status == "planned"
    assert job.chat_group_id == group_id
    assert job.business_key == f"mikan/{batch.id}"
    assert job.payload["at_user_ids"] == ["u-chs"]
    assert "release-1" in str(job.payload["text"])
    assert NOW.isoformat() in str(job.payload["text"])
    assert job.expires_at == NOW + timedelta(hours=24)


async def test_batch_older_than_24_hours_is_suppressed(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_target(sessions)
    first = MikanReleasePipeline(
        sessions=sessions,
        client=FakeMikanClient([_feed()]),
        outbox=OutboxRepository(sessions),
    )
    await first.run_once(NOW)

    restarted = MikanReleasePipeline(
        sessions=sessions,
        client=FakeMikanClient([_feed(not_modified=True)]),
        outbox=OutboxRepository(sessions),
    )
    result = await restarted.run_once(NOW + timedelta(hours=25))

    assert result.batches_closed == 1
    async with sessions() as session:
        batch = (await session.execute(select(ReleaseBatch))).scalar_one()
        job_count = await session.scalar(select(func.count()).select_from(NotificationJob))
    assert batch.status == "suppressed"
    assert job_count == 0


async def test_operator_can_register_confirmed_mikan_mapping(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    anime_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            Anime(
                id=anime_id,
                nsfw_flag="false",
                disabled=False,
                display_title="Needs Mapping",
                created_at=NOW,
                updated_at=NOW,
            )
        )

    entry_id = await _register_mikan_link(
        sessions,
        anime_id=anime_id,
        mikan_id=456,
    )
    same_entry_id = await _register_mikan_link(
        sessions,
        anime_id=anime_id,
        mikan_id=456,
    )

    async with sessions() as session:
        entry = await session.get(ExternalEntry, entry_id)
        link = (
            await session.execute(
                select(AnimeSourceLink).where(AnimeSourceLink.external_entry_id == entry_id)
            )
        ).scalar_one()
    assert same_entry_id == entry_id
    assert entry is not None
    assert entry.provider == "mikan"
    assert entry.external_id == "456"
    assert link.status == "confirmed"
