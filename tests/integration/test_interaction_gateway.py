from __future__ import annotations

import os

import pytest
from anime_tracking_plugin.event_envelope import EventEnvelope
from anime_tracking_plugin.interaction_gateway import InteractionGateway
from anime_tracking_plugin.lifecycle import PluginLifecycle
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def lifecycle():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "TRUNCATE TABLE admin_audit_events, interaction_sessions, "
            "group_runtime_settings, group_memberships, chat_groups, "
            "airing_occurrences, animes RESTART IDENTITY CASCADE"
        )
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    value = PluginLifecycle(
        config={
            "interaction_gateway_enabled": True,
            "admin_page_writes_enabled": True,
        },
        start_dispatcher=False,
    )
    value.sessions = sessions
    try:
        yield value
    finally:
        await engine.dispose()


def _envelope(
    text: str,
    *,
    mentions_bot: bool = False,
    role: str = "member",
) -> EventEnvelope:
    return EventEnvelope(
        platform="qq",
        group_id="100",
        user_id="200",
        display_name="alice",
        role=role,
        self_id="bot",
        message_id="message",
        unified_msg_origin="umo:100",
        text=text,
        mentions_bot=mentions_bot,
        reply_to_message_id=None,
    )


async def test_ordinary_chat_and_default_direct_shortcut_are_silent(lifecycle) -> None:
    gateway = InteractionGateway(lifecycle)

    ordinary = await gateway.route(_envelope("今天看的番剧真不错"))
    direct = await gateway.route(_envelope("今日番剧"))

    assert ordinary.matched is False
    assert direct.matched is False


async def test_mention_query_works_without_enabling_direct_shortcuts(lifecycle) -> None:
    result = await InteractionGateway(lifecycle).route(_envelope("今天有什么番", mentions_bot=True))

    assert result.matched is True
    assert "今天" in (result.text or "")


async def test_only_astrbot_admin_can_change_group_policy(lifecycle) -> None:
    gateway = InteractionGateway(lifecycle)
    denied = await gateway.route(_envelope("开启短命令", mentions_bot=True, role="member"))
    assert denied.text == "仅机器人所有者可修改本群设置。"

    changed = await gateway.route(_envelope("开启短命令", mentions_bot=True, role="admin"))
    assert changed.text == "本群设置已更新。"
    direct = await gateway.route(_envelope("今日番剧"))
    assert direct.matched is True
