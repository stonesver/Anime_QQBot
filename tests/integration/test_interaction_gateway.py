from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from anime_tracking_plugin.adapter import Reply
from anime_tracking_plugin.event_envelope import EventEnvelope
from anime_tracking_plugin.interaction_gateway import InteractionGateway
from anime_tracking_plugin.lifecycle import PluginLifecycle
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from anime_qqbot.groups.repository_v2 import ChatGroupRepository
from anime_qqbot.groups.settings import GroupRuntimeSettingsRepository, LLMMode
from anime_qqbot.interactions.mention_policy import MentionCommandPolicyRepository
from anime_qqbot.persistence.models.catalog import Anime


@pytest.fixture
async def lifecycle():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "TRUNCATE TABLE admin_audit_events, interaction_sessions, "
            "mention_command_policies, group_runtime_settings, group_memberships, chat_groups, "
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


async def test_deterministic_mention_bypasses_disabled_legacy_gateway(lifecycle) -> None:
    lifecycle.config["interaction_gateway_enabled"] = False

    fixed = await InteractionGateway(lifecycle).route(_envelope("今天播什么", mentions_bot=True))
    open_ended = await InteractionGateway(lifecycle).route(
        _envelope("你觉得这部番怎么样", mentions_bot=True)
    )

    assert fixed.matched is True
    assert fixed.stop_propagation is True
    assert open_ended.matched is False


async def test_disabled_llm_mode_rejects_open_mention_without_provider(lifecycle) -> None:
    gateway = InteractionGateway(lifecycle)
    await gateway.route(_envelope("先登记这个群"))
    assert lifecycle.sessions is not None
    group = await ChatGroupRepository(lifecycle.sessions).find_by_external("qq", "100")
    assert group is not None
    settings = GroupRuntimeSettingsRepository(lifecycle.sessions)
    initial = await settings.get_policy(group.id)
    await settings.update_policy(
        group.id,
        expected_version=initial.version,
        now=datetime.now(UTC),
        llm_mode=LLMMode.DISABLED,
    )

    result = await gateway.route(_envelope("你觉得这部番怎么样", mentions_bot=True))

    assert result.matched is True
    assert result.stop_propagation is True
    assert "未启用 LLM" in (result.text or "")


async def test_global_custom_mention_alias_replaces_default_for_every_group(lifecycle) -> None:
    assert lifecycle.sessions is not None
    policies = MentionCommandPolicyRepository(lifecycle.sessions)
    initial = await policies.get()
    aliases = initial.to_mapping()
    aliases["today"] = ["今天更新啥"]
    await policies.update(
        aliases,
        expected_version=initial.version,
        now=datetime.now(UTC),
    )

    gateway = InteractionGateway(lifecycle)
    old_phrase = await gateway.route(_envelope("今天播什么", mentions_bot=True))
    custom_phrase = await gateway.route(_envelope("今天更新啥", mentions_bot=True))

    assert old_phrase.matched is False
    assert custom_phrase.matched is True
    assert custom_phrase.stop_propagation is True


async def test_only_astrbot_admin_can_change_group_policy(lifecycle) -> None:
    gateway = InteractionGateway(lifecycle)
    denied = await gateway.route(_envelope("开启短命令", mentions_bot=True, role="member"))
    assert denied.text == "仅机器人所有者可修改本群设置。"

    changed = await gateway.route(_envelope("开启短命令", mentions_bot=True, role="admin"))
    assert changed.text == "本群设置已更新。"
    direct = await gateway.route(_envelope("今日番剧"))
    assert direct.matched is True


async def test_mention_unique_search_preserves_image_reply(lifecycle) -> None:
    anime_id = uuid4()
    now = datetime.now(UTC)
    assert lifecycle.sessions is not None
    async with lifecycle.sessions() as session, session.begin():
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

    class Builder:
        async def build(self, **_kwargs):
            return Reply.from_image(Path("/var/lib/anime-qqbot/cards/renders/card.png"))

    lifecycle.card_reply_factory = Builder()
    result = await InteractionGateway(lifecycle).route(
        _envelope("搜番 夏日物语", mentions_bot=True)
    )

    assert result.matched is True
    assert result.reply is not None
    assert result.reply.kind == "image"
