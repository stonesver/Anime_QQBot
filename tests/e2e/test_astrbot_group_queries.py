"""E2E tests for group queries through the AstrBot adapter (Task 9).

Uses the EventAdapter with stub handlers to validate the full chain:
message -> parse -> ChatContext -> handler -> Reply -> render.
"""

from __future__ import annotations

import pytest

from astrbot_plugin_anime_tracking.anime_tracking_plugin.adapter import (
    EventAdapter,
    Reply,
    ReplyBlock,
)


async def _today_handler(ctx, intent) -> Reply:
    return Reply(kind="text", blocks=[ReplyBlock(text=f"today {intent.query or ''}")])


async def _week_handler(ctx, intent) -> Reply:
    return Reply(kind="text", blocks=[ReplyBlock(text=f"week group={ctx.group_id}")])


async def _search_handler(ctx, intent) -> Reply:
    if intent.query == "Ambiguous":
        return Reply(
            kind="candidates",
            candidates=["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeee1 Title A"],
        )
    return Reply(kind="text", blocks=[ReplyBlock(text=f"found: {intent.query}")])


async def _detail_handler(ctx, intent) -> Reply:
    if intent.anime_id:
        return Reply(
            kind="text",
            blocks=[ReplyBlock(text=f"detail anime_id={intent.anime_id}")],
        )
    return Reply(kind="text", blocks=[ReplyBlock(text=f"detail query={intent.query}")])


async def _next_handler(ctx, intent) -> Reply:
    return Reply(kind="text", blocks=[ReplyBlock(text="next: T+3d 20:00")])


HANDLERS = {
    "today": _today_handler,
    "week": _week_handler,
    "season": _search_handler,
    "search": _search_handler,
    "detail": _detail_handler,
    "next": _next_handler,
}


@pytest.fixture
def adapter() -> EventAdapter:
    return EventAdapter(handlers=HANDLERS)


@pytest.mark.asyncio
async def test_today_query(adapter: EventAdapter) -> None:
    reply = await adapter.handle_message(
        platform="qq",
        group_id="1",
        user_id="1",
        display_name="u",
        unified_msg_origin=None,
        content="/番剧 今天 2026-07-15",
    )
    assert "today 2026-07-15" in reply.blocks[0].text


@pytest.mark.asyncio
async def test_week_query(adapter: EventAdapter) -> None:
    reply = await adapter.handle_message(
        platform="qq",
        group_id="42",
        user_id="1",
        display_name="u",
        unified_msg_origin=None,
        content="/番剧 本周",
    )
    assert "group=42" in reply.blocks[0].text


@pytest.mark.asyncio
async def test_season_query(adapter: EventAdapter) -> None:
    reply = await adapter.handle_message(
        platform="qq",
        group_id="1",
        user_id="1",
        display_name="u",
        unified_msg_origin=None,
        content="/番剧 季度 2026 夏",
    )
    assert reply.kind == "text"


@pytest.mark.asyncio
async def test_search_query(adapter: EventAdapter) -> None:
    reply = await adapter.handle_message(
        platform="qq",
        group_id="1",
        user_id="1",
        display_name="u",
        unified_msg_origin=None,
        content="/番剧 搜索 夏日",
    )
    assert "found: 夏日" in reply.blocks[0].text


@pytest.mark.asyncio
async def test_detail_with_internal_id(adapter: EventAdapter) -> None:
    reply = await adapter.handle_message(
        platform="qq",
        group_id="1",
        user_id="1",
        display_name="u",
        unified_msg_origin=None,
        content="/番剧 详情 aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeee1",
    )
    assert "anime_id=" in reply.blocks[0].text


@pytest.mark.asyncio
async def test_detail_with_keyword(adapter: EventAdapter) -> None:
    reply = await adapter.handle_message(
        platform="qq",
        group_id="1",
        user_id="1",
        display_name="u",
        unified_msg_origin=None,
        content="/番剧 详情 夏日物语",
    )
    assert "query=夏日物语" in reply.blocks[0].text


@pytest.mark.asyncio
async def test_multi_candidate_returns_candidates_list(adapter: EventAdapter) -> None:
    reply = await adapter.handle_message(
        platform="qq",
        group_id="1",
        user_id="1",
        display_name="u",
        unified_msg_origin=None,
        content="/番剧 搜索 Ambiguous",
    )
    assert reply.candidates
    # internal id in candidate text
    assert "aaaaaaaa" in reply.candidates[0]


@pytest.mark.asyncio
async def test_next_airing_query(adapter: EventAdapter) -> None:
    reply = await adapter.handle_message(
        platform="qq",
        group_id="1",
        user_id="1",
        display_name="u",
        unified_msg_origin=None,
        content="/番剧 下次 aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeee1",
    )
    assert "next:" in reply.blocks[0].text


@pytest.mark.asyncio
async def test_status_query(adapter: EventAdapter) -> None:
    reply = await adapter.handle_message(
        platform="qq",
        group_id="1",
        user_id="1",
        display_name="u",
        unified_msg_origin=None,
        content="/番剧 状态",
    )
    assert reply is not None
