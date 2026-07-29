"""Integration tests for ChatGroupRepository (Task 7)."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from anime_qqbot.groups.repository_v2 import ChatGroupRepository, GroupEvent


def _engine():
    return create_async_engine(os.environ["TEST_DATABASE_URL"])


async def _reset(engine) -> None:
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "TRUNCATE TABLE group_memberships, chat_groups RESTART IDENTITY CASCADE"
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


def _event(
    *,
    platform: str = "qq",
    group: str = "123456",
    user: str = "654321",
    name: str = "alice",
    umo: str | None = "aiocqhttp:123456:msg-1",
    ts: datetime | None = None,
) -> GroupEvent:
    return GroupEvent(
        platform=platform,
        external_group_id=group,
        external_user_id=user,
        display_name=name,
        unified_msg_origin=umo,
        timestamp=ts or datetime(2026, 7, 15, 10, 0, tzinfo=UTC),
    )


async def test_first_event_creates_group_and_membership(session_factory) -> None:
    repo = ChatGroupRepository(session_factory)

    row = await repo.upsert_group_event(_event())

    assert row.platform == "qq"
    assert row.external_group_id == "123456"
    assert row.unified_msg_origin == "aiocqhttp:123456:msg-1"


async def test_stale_umo_does_not_overwrite_fresh_one(session_factory) -> None:
    repo = ChatGroupRepository(session_factory)
    later_ts = datetime(2026, 7, 15, 11, 0, tzinfo=UTC)
    earlier_ts = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)

    await repo.upsert_group_event(_event(umo="fresh", ts=later_ts))
    row = await repo.upsert_group_event(_event(umo="stale", ts=earlier_ts))

    assert row.unified_msg_origin == "fresh"
    assert row.umo_refreshed_at == later_ts


async def test_membership_display_name_updates(session_factory) -> None:
    repo = ChatGroupRepository(session_factory)
    ts1 = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
    ts2 = datetime(2026, 7, 15, 11, 0, tzinfo=UTC)

    await repo.upsert_group_event(_event(name="alice", ts=ts1))
    row = await repo.upsert_group_event(_event(name="Alice", ts=ts2))

    assert row.unified_msg_origin == "aiocqhttp:123456:msg-1"

    engine = _engine()
    async with engine.connect() as conn:
        from sqlalchemy import text

        result = await conn.execute(
            text(
                "SELECT display_name FROM group_memberships "
                "WHERE chat_group_id = :g AND external_user_id = :u"
            ),
            {"g": str(row.id), "u": "654321"},
        )
        name = result.scalar_one()
    await engine.dispose()

    assert name == "Alice"


async def test_disabled_groups_can_still_appear(session_factory) -> None:
    repo = ChatGroupRepository(session_factory)
    row = await repo.upsert_group_event(_event())

    assert row.enabled is True


@pytest.mark.parametrize(
    ("group", "user"),
    [
        ("", "654321"),
        ("123456", ""),
    ],
)
async def test_empty_group_identity_is_rejected(session_factory, group: str, user: str) -> None:
    repo = ChatGroupRepository(session_factory)

    with pytest.raises(ValueError, match="must not be empty"):
        await repo.upsert_group_event(_event(group=group, user=user))


async def test_find_by_external(session_factory) -> None:
    repo = ChatGroupRepository(session_factory)
    await repo.upsert_group_event(_event())

    found = await repo.find_by_external("qq", "123456")

    assert found is not None
    assert found.external_group_id == "123456"


async def test_find_by_external_returns_none_for_unknown(session_factory) -> None:
    repo = ChatGroupRepository(session_factory)

    found = await repo.find_by_external("qq", "unknown")

    assert found is None


async def test_concurrent_events_resolve_to_one_group(session_factory) -> None:
    repo = ChatGroupRepository(session_factory)

    async def _do() -> str:
        row = await repo.upsert_group_event(_event(umo=None))
        return str(row.id)

    ids = await asyncio.gather(*[_do() for _ in range(5)])

    assert len(set(ids)) == 1
