"""Outbox dispatcher contract tests (Task 20 + P0.7)."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from astrbot_plugin_anime_tracking.anime_tracking_plugin.dispatcher import (
    OutboxDispatcher,
)
from astrbot_plugin_anime_tracking.anime_tracking_plugin.lifecycle import (
    PluginLifecycle,
)

SAMPLE_CHAT_GROUP_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
SECOND_CHAT_GROUP_ID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
DB = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://anime:anime@127.0.0.1:55432/anime_test",
)


class FakeContext:
    def __init__(self) -> None:
        self.sent: list[tuple[str, object]] = []

    async def send_message(self, umo: str, chain: object) -> None:
        self.sent.append((umo, chain))


@pytest.fixture
async def _clean() -> None:
    engine = create_async_engine(DB)
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "TRUNCATE TABLE delivery_attempts, notification_jobs, worker_heartbeats, "
                "delivery_controls, group_runtime_settings, "
                "subscription_resource_filters, follow_subscriptions, "
                "source_snapshots, anime_source_links, anime_titles, "
                "airing_occurrences, external_entries, animes, "
                "source_sync_states, chat_groups, group_memberships "
                "RESTART IDENTITY CASCADE"
            )
    finally:
        await engine.dispose()
    yield


@pytest.fixture(autouse=True)
def _ensure_db_url() -> None:
    prev = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = DB
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = prev


async def _seed_chat_group(
    *,
    umo: str | None,
    chat_group_id: UUID = SAMPLE_CHAT_GROUP_ID,
    external_group_id: str = "42",
) -> None:
    from anime_qqbot.persistence.models.identity import ChatGroup

    engine = create_async_engine(DB)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as s, s.begin():
            s.add(
                ChatGroup(
                    id=chat_group_id,
                    platform="qq",
                    external_group_id=external_group_id,
                    unified_msg_origin=umo,
                    timezone="Asia/Shanghai",
                    enabled=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
    finally:
        await engine.dispose()


async def _seed_job(
    *,
    job_type: str = "airing",
    chat_group_id: UUID = SAMPLE_CHAT_GROUP_ID,
) -> UUID:
    from anime_qqbot.persistence.models.notifications_v2 import NotificationJob

    job_id = uuid4()
    engine = create_async_engine(DB)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as s, s.begin():
            s.add(
                NotificationJob(
                    id=job_id,
                    chat_group_id=chat_group_id,
                    job_type=job_type,
                    business_key=f"test-{job_id}",
                    payload={
                        "display_title": "test",
                        "episode_label": "01",
                        "at_user_ids": ["user-1"],
                    },
                    status="pending",
                    available_at=datetime.now(UTC) - timedelta(minutes=1),
                    expires_at=datetime.now(UTC) + timedelta(hours=2),
                    attempt_count=0,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
    finally:
        await engine.dispose()
    return job_id


async def _read_status(job_id: UUID, sessions) -> str:
    async with sessions() as s:
        from anime_qqbot.persistence.models.notifications_v2 import NotificationJob

        job = await s.get(NotificationJob, job_id)
        return job.status


# --------------------------------------------------------------------------- tests


@pytest.mark.asyncio
async def test_dispatcher_calls_send_message_with_db_umo(_clean: None) -> None:
    await _seed_chat_group(umo="umo-real-1")
    job_id = await _seed_job()
    ctx = FakeContext()
    lc = PluginLifecycle(context=ctx, start_dispatcher=False)
    await lc.start()
    d = OutboxDispatcher(lifecycle=lc)
    await d._tick()  # type: ignore[reportPrivateUsage]
    assert len(ctx.sent) == 1
    umo, chain = ctx.sent[0]
    assert umo == "umo-real-1"
    assert hasattr(chain, "chain")
    assert any(item.get("type") == "at" for item in chain.chain)
    assert any(item.get("type") == "plain" for item in chain.chain)
    assert await _read_status(job_id, lc.sessions) == "sent"
    await d.stop()
    await lc.shutdown()


@pytest.mark.asyncio
async def test_dispatcher_marks_failed_when_send_raises(_clean: None) -> None:
    await _seed_chat_group(umo="umo-failing")
    job_id = await _seed_job()

    class RaisingCtx(FakeContext):
        async def send_message(self, umo: str, chain: object) -> None:
            raise RuntimeError("down")

    lc = PluginLifecycle(context=RaisingCtx(), start_dispatcher=False)
    await lc.start()
    d = OutboxDispatcher(lifecycle=lc)
    await d._tick()  # type: ignore[reportPrivateUsage]
    assert await _read_status(job_id, lc.sessions) == "pending"
    await d.stop()
    await lc.shutdown()


@pytest.mark.asyncio
async def test_dispatcher_skips_jobs_without_umo(_clean: None) -> None:
    await _seed_chat_group(umo=None)
    job_id = await _seed_job()
    ctx = FakeContext()
    lc = PluginLifecycle(context=ctx, start_dispatcher=False)
    await lc.start()
    d = OutboxDispatcher(lifecycle=lc)
    await d._tick()  # type: ignore[reportPrivateUsage]
    assert ctx.sent == []
    assert await _read_status(job_id, lc.sessions) == "pending"
    await d.stop()
    await lc.shutdown()


@pytest.mark.asyncio
async def test_paused_group_does_not_block_later_group(_clean: None) -> None:
    from anime_qqbot.notifications.control import DeliveryControlRepository

    await _seed_chat_group(umo="umo-paused")
    paused_job_id = await _seed_job()
    await _seed_chat_group(
        umo="umo-active",
        chat_group_id=SECOND_CHAT_GROUP_ID,
        external_group_id="84",
    )
    active_job_id = await _seed_job(chat_group_id=SECOND_CHAT_GROUP_ID)
    ctx = FakeContext()
    lc = PluginLifecycle(
        context=ctx,
        config={"send_governor_enabled": True},
        start_dispatcher=False,
    )
    await lc.start()
    controls = DeliveryControlRepository(lc.sessions)
    await controls.pause(
        "group",
        "42",
        reason="maintenance",
        now=datetime.now(UTC),
    )

    d = OutboxDispatcher(lifecycle=lc)
    await d._tick()  # type: ignore[reportPrivateUsage]

    assert len(ctx.sent) == 1
    assert ctx.sent[0][0] == "umo-active"
    assert await _read_status(paused_job_id, lc.sessions) == "pending"
    assert await _read_status(active_job_id, lc.sessions) == "sent"
    await d.stop()
    await lc.shutdown()


@pytest.mark.asyncio
async def test_two_dispatchers_do_not_double_claim(_clean: None) -> None:
    await _seed_chat_group(umo="umo-shared")
    await _seed_job()
    ctx_a, ctx_b = FakeContext(), FakeContext()
    lc_a = PluginLifecycle(context=ctx_a, start_dispatcher=False)
    await lc_a.start()
    lc_b = PluginLifecycle(context=ctx_b, start_dispatcher=False)
    await lc_b.start()
    da = OutboxDispatcher(lifecycle=lc_a)
    db = OutboxDispatcher(lifecycle=lc_b)
    await da._tick()  # type: ignore[reportPrivateUsage]
    await db._tick()  # type: ignore[reportPrivateUsage]
    sent = len(ctx_a.sent) + len(ctx_b.sent)
    assert sent == 1, f"got {sent}"
    await da.stop()
    await db.stop()
    await lc_a.shutdown()
    await lc_b.shutdown()


@pytest.mark.asyncio
async def test_lifecycle_starts_live_dispatcher_and_records_heartbeat(_clean: None) -> None:
    from anime_qqbot.persistence.models.runtime import WorkerHeartbeat

    lc = PluginLifecycle(context=FakeContext())
    await lc.start()
    await asyncio.sleep(0.05)

    async with lc.sessions() as session:
        heartbeat = await session.get(WorkerHeartbeat, "astrbot-dispatcher")

    assert heartbeat is not None
    assert heartbeat.worker_kind == "consumer"
    await lc.shutdown()
