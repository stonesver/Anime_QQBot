from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from anime_qqbot.application.context import ChatContext
from anime_qqbot.presentation.models import AnimeCardData, CardScene
from anime_qqbot.presentation.renderer import RenderResult
from astrbot_plugin_anime_tracking.anime_tracking_plugin.adapter import Reply
from astrbot_plugin_anime_tracking.anime_tracking_plugin.card_reply_factory import (
    CardReplyFactory,
)


class Assembler:
    def __init__(self, data: AnimeCardData | None) -> None:
        self.data = data

    async def assemble(self, anime_id, *, timezone, now):
        return self.data


class Renderer:
    def __init__(self, result: RenderResult) -> None:
        self.result = result

    async def render_cached(self, data, poster_path):
        return self.result


def data(anime_id: UUID) -> AnimeCardData:
    return AnimeCardData(
        anime_id=anime_id,
        display_title="夏日物语",
        title_jp="夏物語",
        release_year=2026,
        season_name="夏",
        media_format="TV",
        next_airing=None,
        bangumi_score=8.2,
        total_episodes=12,
        airing_status=None,
        sources=("bangumi", "anilist"),
        timezone_name="Asia/Shanghai",
        projection_fingerprint="digest",
    )


def context() -> ChatContext:
    return ChatContext(
        platform="qq",
        group_id="group",
        user_id="user",
        display_name="alice",
        unified_msg_origin=None,
        timezone=ZoneInfo("Asia/Shanghai"),
    )


async def test_returns_image_and_one_line_hint_when_local_render_succeeds(
    tmp_path: Path,
) -> None:
    anime_id = uuid4()
    poster = tmp_path / "poster.png"
    card = tmp_path / "card.png"
    poster.touch()
    card.touch()
    factory = CardReplyFactory(
        assembler=Assembler(data(anime_id)),  # type: ignore[arg-type]
        poster_locator=lambda _anime_id: poster,
        renderer=Renderer(RenderResult(card)),  # type: ignore[arg-type]
    )

    reply = await factory.build(
        scene=CardScene.DETAIL,
        anime_id=anime_id,
        ctx=context(),
        fallback=Reply.from_text("old fallback"),
        now=datetime(2026, 7, 29, tzinfo=UTC),
    )

    assert reply.kind == "image"
    assert reply.blocks[0].image_path == card
    assert reply.blocks[1].text == "追番时发送「追番 夏日物语」"


async def test_missing_poster_returns_complete_structured_text(tmp_path: Path) -> None:
    anime_id = uuid4()
    factory = CardReplyFactory(
        assembler=Assembler(data(anime_id)),  # type: ignore[arg-type]
        poster_locator=lambda _anime_id: None,
        renderer=Renderer(RenderResult(tmp_path / "unused.png")),  # type: ignore[arg-type]
    )

    reply = await factory.build(
        scene=CardScene.NEXT,
        anime_id=anime_id,
        ctx=context(),
        fallback=Reply.from_text("old fallback"),
        now=datetime(2026, 7, 29, tzinfo=UTC),
    )

    assert reply.kind == "text"
    assert "夏日物语" in reply.blocks[0].text
    assert "Bangumi 8.2" in reply.blocks[0].text
    assert "全 12 集" in reply.blocks[0].text
    assert "待定 · 暂无已知下一集" in reply.blocks[0].text
    assert all(block.image_path is None for block in reply.blocks)
