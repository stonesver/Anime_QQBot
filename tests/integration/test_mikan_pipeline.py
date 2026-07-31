from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from anime_qqbot.entrypoints.cli import _discover_mikan_links, _register_mikan_link
from anime_qqbot.notifications.outbox import OutboxRepository
from anime_qqbot.persistence.models.catalog import Anime, AnimeSourceLink, ExternalEntry
from anime_qqbot.persistence.models.identity import ChatGroup
from anime_qqbot.persistence.models.notifications_v2 import NotificationJob
from anime_qqbot.persistence.models.resources import MikanFeedState, ReleaseBatch, ResourceRelease
from anime_qqbot.persistence.models.subscriptions_v2 import (
    FollowSubscription,
    SubscriptionResourceFilter,
)
from anime_qqbot.resources.adapters.mikan import (
    MikanAnimeEntry,
    MikanFeedResult,
    MikanItem,
)
from anime_qqbot.resources.module import MikanReleasePipeline

RSS_URL = "https://mikanani.me/RSS/Bangumi?bangumiId=123"
DOMESTIC_RSS_URL = "https://mikanime.tv/RSS/Bangumi?bangumiId=123"
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


def _feed(
    *,
    guid: str = "release-1",
    pub_date: datetime = NOW,
    not_modified: bool = False,
) -> MikanFeedResult:
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
                guid=guid,
                title="[Group A] Example Anime [01][1080p][简日]",
                pub_date=pub_date,
                page_url=f"https://mikanani.me/Home/Episode/{guid}",
            ),
        ),
        etag='"v1"',
        last_modified="Tue, 28 Jul 2026 12:00:00 GMT",
    )


async def test_poll_deduplicates_feed_and_persists_baseline(
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
        (DOMESTIC_RSS_URL, None, None),
        (DOMESTIC_RSS_URL, '"v1"', "Tue, 28 Jul 2026 12:00:00 GMT"),
    ]
    async with sessions() as session:
        release_count = await session.scalar(select(func.count()).select_from(ResourceRelease))
        batch_count = await session.scalar(select(func.count()).select_from(ReleaseBatch))
        state = await session.get(MikanFeedState, "mikan:123")
    assert release_count == 1
    assert batch_count == 0
    assert state is not None
    assert state.etag == '"v1"'


async def test_initial_successful_poll_baselines_historical_episodes_without_opening_batches(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_target(sessions)
    historical_feed = MikanFeedResult(
        items=tuple(
            MikanItem(
                guid=f"historical-release-{episode}",
                title=f"[Group A] Example Anime [{episode:02d}][1080p][简日]",
                pub_date=NOW - timedelta(days=episode),
                page_url=f"https://mikanani.me/Home/Episode/historical-release-{episode}",
            )
            for episode in range(1, 7)
        ),
        etag='"baseline"',
        last_modified="Tue, 21 Jul 2026 12:00:00 GMT",
    )
    pipeline = MikanReleasePipeline(
        sessions=sessions,
        client=FakeMikanClient([historical_feed]),
        outbox=OutboxRepository(sessions),
    )

    result = await pipeline.run_once(NOW)

    assert result.releases_created == 6
    async with sessions() as session:
        release_count = await session.scalar(select(func.count()).select_from(ResourceRelease))
        batch_count = await session.scalar(select(func.count()).select_from(ReleaseBatch))
        job_count = await session.scalar(select(func.count()).select_from(NotificationJob))
    assert release_count == 6
    assert batch_count == 0
    assert job_count == 0


async def test_established_feed_does_not_open_batch_for_release_older_than_24_hours(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_target(sessions)
    empty_baseline = MikanFeedResult(
        items=(),
        etag='"baseline"',
        last_modified="Tue, 28 Jul 2026 11:55:00 GMT",
    )
    stale_update = MikanFeedResult(
        items=(
            MikanItem(
                guid="late-discovered-release",
                title="[Group A] Example Anime [01][1080p][简日]",
                pub_date=NOW - timedelta(hours=25),
                page_url="https://mikanani.me/Home/Episode/late-discovered-release",
            ),
        ),
        etag='"update"',
        last_modified="Tue, 28 Jul 2026 12:05:00 GMT",
    )
    pipeline = MikanReleasePipeline(
        sessions=sessions,
        client=FakeMikanClient([empty_baseline, stale_update]),
        outbox=OutboxRepository(sessions),
    )

    await pipeline.run_once(NOW)
    result = await pipeline.run_once(NOW + timedelta(minutes=5))

    assert result.releases_created == 1
    async with sessions() as session:
        release_count = await session.scalar(select(func.count()).select_from(ResourceRelease))
        batch_count = await session.scalar(select(func.count()).select_from(ReleaseBatch))
        job_count = await session.scalar(select(func.count()).select_from(NotificationJob))
    assert release_count == 1
    assert batch_count == 0
    assert job_count == 0


async def test_restart_closes_batch_and_enqueues_filtered_group_job(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    _, group_id = await _seed_target(sessions)
    release_pub_date = NOW + timedelta(minutes=4)
    first = MikanReleasePipeline(
        sessions=sessions,
        client=FakeMikanClient(
            [
                MikanFeedResult(items=(), etag='"baseline"', last_modified=None),
                _feed(guid="fresh-release", pub_date=release_pub_date),
            ]
        ),
        outbox=OutboxRepository(sessions),
    )
    await first.run_once(NOW)
    await first.run_once(NOW + timedelta(minutes=5))

    restarted = MikanReleasePipeline(
        sessions=sessions,
        client=FakeMikanClient([_feed(not_modified=True)]),
        outbox=OutboxRepository(sessions),
    )
    result = await restarted.run_once(NOW + timedelta(minutes=15))

    assert result.batches_closed == 1
    async with sessions() as session:
        batch = (await session.execute(select(ReleaseBatch))).scalar_one()
        job = (await session.execute(select(NotificationJob))).scalar_one()
    assert batch.status == "planned"
    assert job.chat_group_id == group_id
    assert job.business_key == f"mikan/{batch.id}"
    assert job.payload["at_user_ids"] == ["u-chs"]
    assert "text" not in job.payload
    assert job.payload["display_title"] == "Example Anime"
    assert job.payload["episode_label"] == "01"
    assert job.payload["release_count"] == 1
    assert job.payload["detail_query"] == "Example Anime"
    assert job.payload["releases"] == [
        {
            "subtitle_group": "Group A",
            "language": "chs",
            "resolution": "1080p",
            "pub_date": release_pub_date.isoformat(),
        }
    ]
    assert "http://" not in str(job.payload)
    assert "https://" not in str(job.payload)
    assert "fresh-release" not in str(job.payload)
    assert job.expires_at == release_pub_date + timedelta(hours=24)


async def test_batch_older_than_24_hours_is_suppressed(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_target(sessions)
    first = MikanReleasePipeline(
        sessions=sessions,
        client=FakeMikanClient(
            [
                MikanFeedResult(items=(), etag='"baseline"', last_modified=None),
                _feed(guid="fresh-release", pub_date=NOW + timedelta(minutes=5)),
            ]
        ),
        outbox=OutboxRepository(sessions),
    )
    await first.run_once(NOW)
    await first.run_once(NOW + timedelta(minutes=5))

    restarted = MikanReleasePipeline(
        sessions=sessions,
        client=FakeMikanClient([_feed(not_modified=True)]),
        outbox=OutboxRepository(sessions),
    )
    result = await restarted.run_once(NOW + timedelta(hours=25, minutes=5))

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


async def test_discovery_confirms_mapping_only_when_public_cross_id_matches(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    anime_id = uuid4()
    bangumi_entry_id = uuid4()
    group_id = uuid4()
    title = "感谢对战。 ～大小姐才不玩格斗游戏～"
    async with sessions() as session, session.begin():
        session.add(
            Anime(
                id=anime_id,
                nsfw_flag="false",
                disabled=False,
                display_title=title,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            ExternalEntry(
                id=bangumi_entry_id,
                provider="bangumi",
                external_id="325767",
                url="https://bgm.tv/subject/325767",
                disabled=False,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            AnimeSourceLink(
                id=uuid4(),
                anime_id=anime_id,
                external_entry_id=bangumi_entry_id,
                status="confirmed",
                evidence_type="manual",
                confidence=1.0,
                method="fixture",
                created_at=NOW,
            )
        )
        session.add(
            ChatGroup(
                id=group_id,
                platform="qq",
                external_group_id="43",
                unified_msg_origin="umo:43",
                timezone="Asia/Shanghai",
                enabled=True,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            FollowSubscription(
                id=uuid4(),
                chat_group_id=group_id,
                external_user_id="u-resource",
                anime_id=anime_id,
                notify_airing=True,
                notify_resource=True,
                created_at=NOW,
            )
        )

    class _DiscoveryClient:
        async def discover_current_anime(self) -> tuple[MikanAnimeEntry, ...]:
            return (MikanAnimeEntry(mikan_id=4035, title=title),)

        async def fetch_bangumi_subject_id(self, mikan_id: int) -> int | None:
            assert mikan_id == 4035
            return 325767

    created = await _discover_mikan_links(
        sessions,
        _DiscoveryClient(),
        now=NOW,
        limit=10,
    )

    assert created == 1
    async with sessions() as session:
        entry = (
            await session.execute(
                select(ExternalEntry).where(
                    ExternalEntry.provider == "mikan",
                    ExternalEntry.external_id == "4035",
                )
            )
        ).scalar_one()
        link = (
            await session.execute(
                select(AnimeSourceLink).where(AnimeSourceLink.external_entry_id == entry.id)
            )
        ).scalar_one()
    assert entry.url == "https://mikanime.tv/Home/Bangumi/4035"
    assert link.anime_id == anime_id
    assert link.status == "confirmed"
    assert link.evidence_type == "mikan_bangumi_link"
