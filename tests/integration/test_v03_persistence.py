from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from anime_tracking_plugin.astrbot_tool import AnimeReadonlyTool
from anime_tracking_plugin.lifecycle import PluginLifecycle
from anime_tracking_plugin.llm_policy import LLMPolicyGuard
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from anime_qqbot.groups.repository_v2 import ChatGroupRepository, GroupEvent
from anime_qqbot.groups.settings import (
    GroupRuntimeSettingsRepository,
    PolicyVersionConflictError,
)
from anime_qqbot.interactions.models import CandidateItem, InteractionScope
from anime_qqbot.interactions.repository import InteractionSessionRepository
from anime_qqbot.notifications.control import DeliveryControlRepository
from anime_qqbot.operations.repository import AdminAuditRepository, OperatorJobRepository


@pytest.fixture
async def session_factory():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "TRUNCATE TABLE admin_audit_events, operator_jobs, delivery_controls, "
            "interaction_sessions, group_runtime_settings, group_memberships, "
            "chat_groups RESTART IDENTITY CASCADE"
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _group(session_factory) -> object:
    return await ChatGroupRepository(session_factory).upsert_group_event(
        GroupEvent(
            platform="qq",
            external_group_id="100",
            external_user_id="200",
            display_name="tester",
            unified_msg_origin="umo:100",
            timestamp=datetime(2026, 7, 29, 8, tzinfo=UTC),
        )
    )


async def test_group_policy_defaults_and_optimistic_update(session_factory) -> None:
    group = await _group(session_factory)
    repo = GroupRuntimeSettingsRepository(session_factory)
    now = datetime(2026, 7, 29, 9, tzinfo=UTC)

    initial = await repo.get_policy(group.id)
    assert initial.general_chat_enabled is False
    assert initial.mention_enabled is True
    assert initial.direct_shortcuts_enabled is False
    assert initial.active_notifications_enabled is True
    assert initial.weekly_report_enabled is False
    assert initial.daily_digest_enabled is False
    assert initial.daily_digest_at_all_enabled is False

    changed = await repo.update_policy(
        group.id,
        expected_version=initial.version,
        now=now,
        general_chat_enabled=True,
        direct_shortcuts_enabled=True,
        weekly_report_enabled=True,
        weekly_report_weekday=0,
        weekly_report_minute=20 * 60,
        daily_digest_enabled=True,
        daily_digest_at_all_enabled=True,
        quiet_start_minute=23 * 60,
        quiet_end_minute=7 * 60,
    )
    assert changed.general_chat_enabled is True
    assert changed.direct_shortcuts_enabled is True
    assert changed.weekly_report_enabled is True
    assert changed.weekly_report_weekday == 0
    assert changed.weekly_report_minute == 20 * 60
    assert changed.daily_digest_enabled is True
    assert changed.daily_digest_at_all_enabled is True
    assert changed.is_quiet_at(datetime(2026, 7, 29, 16, 30, tzinfo=UTC))

    with pytest.raises(PolicyVersionConflictError):
        await repo.update_policy(
            group.id,
            expected_version=initial.version,
            now=now,
            mention_enabled=False,
        )


async def test_readonly_tool_uses_current_event_identity(session_factory) -> None:
    lifecycle = PluginLifecycle(start_dispatcher=False)
    lifecycle.sessions = session_factory
    guard = LLMPolicyGuard()
    event = SimpleNamespace(
        group_id="tool-group",
        message_id="tool-message",
        message_str="我的订阅",
        unified_msg_origin="umo:tool-group",
        role="member",
        message_obj=SimpleNamespace(
            self_id="bot1",
            group_id="tool-group",
            message_id="tool-message",
            sender={"user_id": "tool-user", "nickname": "alice"},
            message=[
                {"type": "At", "data": {"qq": "bot1"}},
                {"type": "Plain", "text": "我的订阅"},
            ],
        ),
    )
    guard.begin(event, general_chat_enabled=False)

    async def lifecycle_provider() -> PluginLifecycle:
        return lifecycle

    tool = AnimeReadonlyTool(
        lifecycle_provider=lifecycle_provider,
        policy_guard=guard,
    )
    raw_result = await tool.call(
        SimpleNamespace(context=SimpleNamespace(event=event)),
        action="my_subscriptions",
    )
    result = json.loads(raw_result)

    assert result["status"] == "not_found"
    assert result["content"] == "你当前没有订阅"
    stored = await ChatGroupRepository(session_factory).find_by_external(
        "qq", "tool-group"
    )
    assert stored is not None


async def test_interaction_session_isolated_and_reply_bound(session_factory) -> None:
    repo = InteractionSessionRepository(session_factory)
    now = datetime(2026, 7, 29, 8, tzinfo=UTC)
    scope = InteractionScope("qq", "100", "200")
    anime_id = uuid4()
    await repo.replace(
        scope,
        [CandidateItem(anime_id=anime_id, title="测试番剧")],
        now=now,
        result_message_id="result-1",
    )

    assert (await repo.resolve(scope, now=now)).candidate(1).anime_id == anime_id
    assert (
        await repo.resolve(
            scope,
            now=now,
            reply_to_message_id="wrong",
            require_reply_match=True,
        )
        is None
    )
    assert (
        await repo.resolve(
            InteractionScope("qq", "100", "other"),
            now=now,
        )
        is None
    )
    assert await repo.resolve(scope, now=now + timedelta(minutes=6)) is None


async def test_delivery_control_survives_reads_and_requires_manual_resume(
    session_factory,
) -> None:
    repo = DeliveryControlRepository(session_factory)
    now = datetime(2026, 7, 29, 8, tzinfo=UTC)

    await repo.open_circuit("group", "100", error="risk control", now=now, failure_count=3)
    assert await repo.permits_group("100") is False

    resumed = await repo.resume("group", "100", actor="astrbot-owner", now=now)
    assert resumed.resumed_by == "astrbot-owner"
    assert await repo.permits_group("100") is True


async def test_operator_jobs_are_idempotent_and_audit_redacts(session_factory) -> None:
    now = datetime(2026, 7, 29, 8, tzinfo=UTC)
    jobs = OperatorJobRepository(session_factory)
    first = await jobs.enqueue(
        "sync_catalog",
        {"source": "bangumi"},
        idempotency_key="sync:2026-07-29",
        now=now,
    )
    second = await jobs.enqueue(
        "sync_catalog",
        {"source": "ignored"},
        idempotency_key="sync:2026-07-29",
        now=now,
    )
    assert first.id == second.id

    claimed = await jobs.claim(worker_id="worker-1", now=now)
    assert claimed is not None
    assert await jobs.complete(
        claimed.id,
        worker_id="worker-1",
        summary={"count": 3, "token": "must-not-leak"},
        now=now,
    )

    audit = await AdminAuditRepository(session_factory).append(
        actor="owner",
        action="group.update",
        target_type="group",
        target_id="100",
        before_summary=None,
        after_summary={"direct": True, "password": "must-not-leak"},
        result="success",
        error_summary=None,
        now=now,
    )
    assert audit.after_summary == {"direct": True, "password": "[REDACTED]"}
