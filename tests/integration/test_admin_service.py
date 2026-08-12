from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from anime_qqbot.application.admin_service import AdminService, AdminValidationError
from anime_qqbot.groups.repository_v2 import ChatGroupRepository, GroupEvent
from anime_qqbot.operations.napcat_status import NapCatProbeResult, NapCatStatusTracker
from anime_qqbot.operations.runtime_status_repository import (
    RuntimeComponentStatusRepository,
)
from anime_qqbot.persistence.models.catalog import (
    AiringOccurrenceRow,
    AniListMappingAssessment,
    Anime,
    AnimeSourceLink,
    ExternalEntry,
    SourceSnapshot,
)
from anime_qqbot.persistence.models.notifications_v2 import NotificationJob
from anime_qqbot.persistence.models.operations import AdminAuditEvent
from anime_qqbot.persistence.models.subscriptions_v2 import FollowSubscription


@pytest.fixture
async def session_factory():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "TRUNCATE TABLE runtime_component_events, runtime_component_states, "
            "admin_audit_events, operator_jobs, delivery_controls, "
            "interaction_sessions, group_runtime_settings, delivery_attempts, "
            "notification_jobs, subscription_resource_filters, follow_subscriptions, "
            "source_snapshots, anime_source_links, anime_titles, airing_occurrences, "
            "external_entries, animes, source_sync_states, group_memberships, "
            "chat_groups, anilist_mapping_policies RESTART IDENTITY CASCADE"
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _seed(session_factory):
    now = datetime(2026, 7, 29, tzinfo=UTC)
    group = await ChatGroupRepository(session_factory).upsert_group_event(
        GroupEvent(
            platform="qq",
            external_group_id="987654321",
            external_user_id="123456789",
            display_name="alice",
            unified_msg_origin="secret-routing-token",
            timestamp=now,
        )
    )
    anime_id = uuid4()
    subscription_id = uuid4()
    async with session_factory() as session, session.begin():
        session.add(
            Anime(
                id=anime_id,
                nsfw_flag="false",
                disabled=False,
                display_title="测试番剧",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            FollowSubscription(
                id=subscription_id,
                chat_group_id=group.id,
                external_user_id="123456789",
                anime_id=anime_id,
                notify_airing=True,
                notify_resource=True,
                created_at=now,
            )
        )
    return group, subscription_id


async def test_admin_read_models_are_safe_and_aggregated(session_factory) -> None:
    await _seed(session_factory)
    service = AdminService(session_factory)

    overview = await service.overview()
    groups = await service.groups()
    subscriptions = await service.subscriptions()

    assert overview["groups"] == 1
    assert overview["subscriptions"] == 1
    assert groups["items"][0]["direct_shortcuts_enabled"] is False
    assert "unified_msg_origin" not in groups["items"][0]
    assert subscriptions["items"][0]["user_id"] == "123…789"


async def test_admin_catalog_exposes_sync_and_airing_coverage(
    session_factory,
) -> None:
    now = datetime(2026, 7, 30, 1, 0, tzinfo=UTC)
    exact_anime_id = uuid4()
    date_only_anime_id = uuid4()
    bangumi_exact_id = uuid4()
    anilist_exact_id = uuid4()
    bangumi_date_only_id = uuid4()
    async with session_factory() as session, session.begin():
        session.add_all(
            [
                Anime(
                    id=exact_anime_id,
                    nsfw_flag="false",
                    disabled=False,
                    display_title="精确目录番剧",
                    created_at=now,
                    updated_at=now,
                ),
                Anime(
                    id=date_only_anime_id,
                    nsfw_flag="false",
                    disabled=False,
                    display_title="日期目录番剧",
                    created_at=now,
                    updated_at=now,
                ),
                ExternalEntry(
                    id=bangumi_exact_id,
                    provider="bangumi",
                    external_id="100",
                    url=None,
                    disabled=False,
                    created_at=now,
                    updated_at=now,
                ),
                ExternalEntry(
                    id=anilist_exact_id,
                    provider="anilist",
                    external_id="200",
                    url=None,
                    disabled=False,
                    created_at=now,
                    updated_at=now,
                ),
                ExternalEntry(
                    id=bangumi_date_only_id,
                    provider="bangumi",
                    external_id="300",
                    url=None,
                    disabled=False,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                AnimeSourceLink(
                    id=uuid4(),
                    anime_id=exact_anime_id,
                    external_entry_id=bangumi_exact_id,
                    status="confirmed",
                    evidence_type="manual",
                    confidence=1.0,
                    method="fixture",
                    created_at=now,
                ),
                AnimeSourceLink(
                    id=uuid4(),
                    anime_id=exact_anime_id,
                    external_entry_id=anilist_exact_id,
                    status="confirmed",
                    evidence_type="title_season_year",
                    confidence=0.9,
                    method="fixture",
                    created_at=now,
                ),
                AnimeSourceLink(
                    id=uuid4(),
                    anime_id=date_only_anime_id,
                    external_entry_id=bangumi_date_only_id,
                    status="confirmed",
                    evidence_type="manual",
                    confidence=1.0,
                    method="fixture",
                    created_at=now,
                ),
                SourceSnapshot(
                    id=uuid4(),
                    external_entry_id=anilist_exact_id,
                    version=1,
                    payload={"title_jp": "Exact"},
                    source_time=now,
                    fetched_at=now,
                    expires_at=None,
                ),
                AiringOccurrenceRow(
                    id=uuid4(),
                    anime_id=exact_anime_id,
                    source_entry_id=anilist_exact_id,
                    episode_label="04",
                    air_date=datetime(2027, 1, 1, tzinfo=UTC).date(),
                    air_at=datetime(2027, 1, 1, 12, 30, tzinfo=UTC),
                    precision="exact",
                    source_event_key="exact-04",
                    updated_at=now,
                ),
                AiringOccurrenceRow(
                    id=uuid4(),
                    anime_id=date_only_anime_id,
                    source_entry_id=bangumi_date_only_id,
                    episode_label="05",
                    air_date=datetime(2027, 1, 2, tzinfo=UTC).date(),
                    air_at=None,
                    precision="date_only",
                    source_event_key="date-only-05",
                    updated_at=now,
                ),
            ]
        )

    service = AdminService(session_factory)
    overview = await service.overview()
    catalog = await service.catalog(query="精确目录")

    assert overview["catalog_animes"] == 2
    assert overview["anilist_mapped"] == 1
    assert overview["future_airing_animes"] == 2
    assert overview["future_exact_animes"] == 1
    assert overview["future_mapped_without_exact_animes"] == 0
    assert overview["future_unmapped_anilist_animes"] == 1
    assert catalog["total"] == 1
    assert catalog["items"] == [
        {
            "id": str(exact_anime_id),
            "title": "精确目录番剧",
            "sources": ["anilist", "bangumi"],
            "anilist_mapped": True,
            "next_air_date": "2027-01-01",
            "next_air_at": "2027-01-01T12:30:00+00:00",
            "next_episode": "04",
            "precision": "exact",
            "last_synced_at": "2026-07-30T01:00:00+00:00",
        }
    ]


async def test_admin_mapping_status_exposes_strict_auto_match_failure(session_factory) -> None:
    now = datetime(2026, 8, 4, tzinfo=UTC)
    anime_id = uuid4()
    async with session_factory() as session, session.begin():
        session.add(
            Anime(
                id=anime_id,
                nsfw_flag="false",
                disabled=False,
                display_title="无精确候选",
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        session.add(
            AniListMappingAssessment(
                anime_id=anime_id,
                status="no_candidate",
                reason="no_exact_candidate",
                candidate_count=0,
                attempted_at=now,
                retry_after=now + timedelta(days=1),
            )
        )

    result = await AdminService(session_factory).mappings()

    assert result["total"] == 1
    assert result["items"] == [
        {
            "kind": "assessment",
            "id": str(anime_id),
            "anime_title": "无精确候选",
            "provider": "anilist",
            "external_id": "—",
            "status": "no_candidate",
            "confidence": None,
            "evidence_type": "no_exact_candidate",
            "method": "anilist_exact_native_date_v1",
            "candidate_count": 0,
            "attempted_at": "2026-08-04T00:00:00+00:00",
        }
    ]


async def test_admin_mapping_policy_is_persisted_and_audited(session_factory) -> None:
    service = AdminService(session_factory)

    assert (await service.mapping_policy())["query_budget"] == 12
    updated = await service.update_mapping_policy(
        actor="owner-hash",
        query_budget=8,
        priority_window_days=5,
        retry_cooldown_hours=12,
    )

    assert updated == {
        "query_budget": 8,
        "priority_window_days": 5,
        "retry_cooldown_hours": 12,
        "animeschedule_enabled": False,
        "animeschedule_query_budget": 12,
        "animeschedule_priority_window_days": 7,
        "animeschedule_empty_cooldown_hours": 168,
        "animeschedule_error_cooldown_hours": 168,
        "matching_rule": "animeschedule_cross_id_then_anilist_strict",
    }
    assert (await service.mapping_policy())["query_budget"] == 8
    async with session_factory() as session:
        actions = (await session.execute(select(AdminAuditEvent.action))).scalars().all()
    assert actions == ["anilist_mapping.policy.update"]


async def test_admin_requires_configured_token_before_enabling_animeschedule(
    session_factory,
) -> None:
    with pytest.raises(AdminValidationError, match="token is not configured"):
        await AdminService(session_factory).update_mapping_policy(
            actor="owner-hash",
            query_budget=12,
            priority_window_days=7,
            retry_cooldown_hours=24,
            animeschedule_enabled=True,
        )

    service = AdminService(session_factory, animeschedule_token_configured=True)
    updated = await service.update_mapping_policy(
        actor="owner-hash",
        query_budget=12,
        priority_window_days=7,
        retry_cooldown_hours=24,
        animeschedule_enabled=True,
        animeschedule_query_budget=9,
        animeschedule_priority_window_days=5,
        animeschedule_empty_cooldown_hours=120,
        animeschedule_error_cooldown_hours=240,
    )

    assert updated["animeschedule_enabled"] is True
    assert updated["animeschedule_query_budget"] == 9
    assert (await service.mapping_policy())["animeschedule_token_configured"] is True


async def test_admin_group_update_and_delivery_control_are_audited(
    session_factory,
) -> None:
    group, _ = await _seed(session_factory)
    service = AdminService(session_factory)

    updated = await service.update_group(
        group.external_group_id,
        actor="owner-hash",
        expected_version=1,
        changes={
            "direct_shortcuts_enabled": True,
            "daily_digest_enabled": True,
            "daily_digest_at_all_enabled": True,
            "weekly_report_enabled": True,
        },
    )
    paused = await service.set_global_delivery(paused=True, actor="owner-hash", reason="canary")

    assert updated["direct_shortcuts_enabled"] is True
    assert updated["daily_digest_enabled"] is True
    assert updated["daily_digest_at_all_enabled"] is True
    assert updated["weekly_report_enabled"] is True
    assert updated["version"] == 2
    assert paused["paused"] is True
    async with session_factory() as session:
        actions = (
            (
                await session.execute(
                    select(AdminAuditEvent.action).order_by(AdminAuditEvent.created_at)
                )
            )
            .scalars()
            .all()
        )
    assert actions == ["group.policy.update", "delivery.pause"]


async def test_bot_owner_can_open_and_close_content_poll_from_admin(session_factory) -> None:
    group, _ = await _seed(session_factory)
    now = datetime(2026, 7, 29, tzinfo=UTC)
    anime_ids = []
    async with session_factory() as session, session.begin():
        for index in range(2):
            anime_id = uuid4()
            anime_ids.append(anime_id)
            session.add(
                Anime(
                    id=anime_id,
                    nsfw_flag="false",
                    disabled=False,
                    display_title=f"投票候选{index + 2}",
                    created_at=now,
                    updated_at=now,
                )
            )
        first = await session.scalar(select(Anime.id).where(Anime.display_title == "测试番剧"))
    assert first is not None

    service = AdminService(session_factory)
    opened = await service.open_content_poll(
        actor="owner-hash",
        external_group_id=group.external_group_id,
        theme="weekly_best",
        anime_ids=[str(first), *(str(value) for value in anime_ids)],
        duration_hours=48,
    )
    polls = await service.content_polls()
    closed = await service.close_content_poll(opened["id"], actor="owner-hash")

    assert polls[0]["status"] == "open"
    assert len(polls[0]["candidates"]) == 3
    assert closed["id"] == opened["id"]
    async with session_factory() as session:
        job_types = (
            (
                await session.execute(
                    select(NotificationJob.job_type).order_by(NotificationJob.job_type)
                )
            )
            .scalars()
            .all()
        )
    assert job_types == ["poll_open", "poll_result"]


async def test_admin_can_cancel_one_subscription(session_factory) -> None:
    _, subscription_id = await _seed(session_factory)

    deleted = await AdminService(session_factory).cancel_subscription(
        str(subscription_id), actor="owner-hash"
    )

    assert deleted is True


async def test_overview_exposes_safe_napcat_status_and_recent_history(
    session_factory,
) -> None:
    started_at = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    tracker = NapCatStatusTracker()
    repository = RuntimeComponentStatusRepository(session_factory)
    await repository.record(
        "napcat",
        tracker.observe(NapCatProbeResult.online(), observed_at=started_at),
    )
    await repository.record(
        "napcat",
        tracker.observe(
            NapCatProbeResult.qq_offline(),
            observed_at=started_at + timedelta(minutes=1),
        ),
    )

    overview = await AdminService(session_factory).overview()

    assert overview["napcat_status"] == {
        "status": "qq_offline",
        "observed_at": "2026-07-29T12:01:00+00:00",
        "status_changed_at": "2026-07-29T12:01:00+00:00",
        "offline_since": "2026-07-29T12:01:00+00:00",
        "recent_events": [
            {
                "previous_status": "online",
                "status": "qq_offline",
                "occurred_at": "2026-07-29T12:01:00+00:00",
            },
            {
                "previous_status": None,
                "status": "online",
                "occurred_at": "2026-07-29T12:00:00+00:00",
            },
        ],
    }
