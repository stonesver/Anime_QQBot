from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from anime_tracking_plugin.adapter import Reply
from anime_tracking_plugin.readonly_tool import (
    ReadonlyAnimeExecutor,
    ReadonlyAnimeRequest,
    ReadonlyToolStatus,
)

from anime_qqbot.application import ChatContext, IntentKind


class FakeReadonlyAdapter:
    def __init__(self, reply: Reply) -> None:
        self.reply = reply
        self.persisted = False
        self.intent = None

    async def handle_intent(self, *, ctx, intent, now=None):
        self.intent = intent
        return self.reply

    async def persist_candidates(self, *, ctx, reply, now, result_message_id=None):
        self.persisted = True


@pytest.mark.parametrize(
    ("payload", "kind", "expected"),
    [
        ({"action": "today", "date": "2026-08-12"}, IntentKind.TODAY, "2026-08-12"),
        ({"action": "week"}, IntentKind.WEEK, None),
        (
            {"action": "season", "year": 2026, "season": "夏"},
            IntentKind.SEASON,
            (2026, "summer"),
        ),
        ({"action": "search", "query": "胆大党"}, IntentKind.SEARCH, "胆大党"),
        ({"action": "detail", "selection": 2}, IntentKind.DETAIL, 2),
        (
            {"action": "resource_detail", "query": "胆大党", "episode": "12"},
            IntentKind.RESOURCE_DETAIL,
            ("胆大党", "12"),
        ),
        ({"action": "next", "query": "胆大党"}, IntentKind.NEXT, "胆大党"),
        ({"action": "my_subscriptions"}, IntentKind.MY_SUBSCRIPTIONS, None),
    ],
)
def test_readonly_request_maps_only_to_approved_intents(payload, kind, expected) -> None:
    intent = ReadonlyAnimeRequest.from_tool_args(**payload).to_intent()

    assert intent.kind == kind
    if kind == IntentKind.TODAY:
        assert intent.query == expected
    elif kind == IntentKind.SEASON:
        assert (intent.season_year, intent.season_name) == expected
    elif kind == IntentKind.DETAIL:
        assert intent.selection_number == expected
    elif kind == IntentKind.RESOURCE_DETAIL:
        assert (intent.query, intent.episode_label) == expected
    elif kind in {IntentKind.SEARCH, IntentKind.NEXT}:
        assert intent.query == expected


def test_readonly_request_rejects_write_action() -> None:
    with pytest.raises(ValueError, match="unsupported readonly action"):
        ReadonlyAnimeRequest.from_tool_args(action="subscribe", query="胆大党")


def test_search_cannot_use_candidate_number_without_a_query() -> None:
    with pytest.raises(ValueError, match="search requires query"):
        ReadonlyAnimeRequest.from_tool_args(action="search", selection=1)


@pytest.mark.asyncio
async def test_executor_persists_and_returns_numbered_candidates() -> None:
    adapter = FakeReadonlyAdapter(
        Reply.from_candidates(
            (
                SimpleNamespace(id=uuid4(), display_title="胆大党 第一季"),
                SimpleNamespace(id=uuid4(), display_title="胆大党 第二季"),
            )
        )
    )
    executor = ReadonlyAnimeExecutor(adapter)
    context = ChatContext(
        platform="qq",
        group_id="100",
        user_id="200",
        display_name="tester",
        unified_msg_origin="umo:100",
        timezone=ZoneInfo("Asia/Shanghai"),
    )

    outcome = await executor.execute(
        ctx=context,
        request=ReadonlyAnimeRequest.from_tool_args(action="search", query="胆大党"),
        now=datetime(2026, 8, 12, tzinfo=UTC),
    )

    result = outcome.result
    assert result.status == ReadonlyToolStatus.OK
    assert result.content == "1. 胆大党 第一季\n2. 胆大党 第二季"
    assert result.candidate_count == 2
    assert adapter.persisted is True

    payload = json.loads(result.to_json())
    assert payload["status"] == "ok"
    assert payload["action"] == "search"
    assert payload["candidate_count"] == 2


@pytest.mark.asyncio
async def test_executor_resolves_current_season_in_group_timezone() -> None:
    adapter = FakeReadonlyAdapter(Reply.from_text("季度番剧"))
    executor = ReadonlyAnimeExecutor(adapter)
    context = ChatContext(
        platform="qq",
        group_id="100",
        user_id="200",
        display_name="tester",
        unified_msg_origin="umo:100",
        timezone=ZoneInfo("Asia/Shanghai"),
    )

    await executor.execute(
        ctx=context,
        request=ReadonlyAnimeRequest.from_tool_args(action="season"),
        now=datetime(2026, 8, 12, tzinfo=UTC),
    )

    assert adapter.intent.season_year == 2026
    assert adapter.intent.season_name == "summer"


@pytest.mark.asyncio
async def test_executor_preserves_image_reply_and_its_model_text_fallback(tmp_path) -> None:
    image = tmp_path / "today.png"
    image.touch()
    adapter = FakeReadonlyAdapter(Reply.from_image(image, fallback_text="今日放送：测试番剧"))
    executor = ReadonlyAnimeExecutor(adapter)
    context = ChatContext(
        platform="qq",
        group_id="100",
        user_id="200",
        display_name="tester",
        unified_msg_origin="umo:100",
        timezone=ZoneInfo("Asia/Shanghai"),
    )

    outcome = await executor.execute(
        ctx=context,
        request=ReadonlyAnimeRequest.from_tool_args(action="today"),
        now=datetime(2026, 8, 13, tzinfo=UTC),
    )

    assert outcome.result.content == "今日放送：测试番剧"
    assert outcome.reply.kind == "image"
    assert outcome.reply.blocks[0].image_path == image
