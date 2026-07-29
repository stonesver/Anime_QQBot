from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from anime_qqbot.application.admin_service import AdminService
from anime_qqbot.groups.repository_v2 import ChatGroupRepository, GroupEvent
from anime_qqbot.operations.napcat_status import NapCatProbeResult, NapCatStatusTracker
from anime_qqbot.operations.runtime_status_repository import (
    RuntimeComponentStatusRepository,
)
from anime_qqbot.persistence.models.catalog import Anime
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
            "chat_groups RESTART IDENTITY CASCADE"
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


async def test_admin_group_update_and_delivery_control_are_audited(
    session_factory,
) -> None:
    group, _ = await _seed(session_factory)
    service = AdminService(session_factory)

    updated = await service.update_group(
        group.external_group_id,
        actor="owner-hash",
        expected_version=1,
        changes={"direct_shortcuts_enabled": True},
    )
    paused = await service.set_global_delivery(paused=True, actor="owner-hash", reason="canary")

    assert updated["direct_shortcuts_enabled"] is True
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
