from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from uuid import UUID

from anime_qqbot.application.context import ChatContext
from anime_qqbot.presentation.assembler import CardDataAssembler
from anime_qqbot.presentation.models import CardScene, card_scene_allows_image
from anime_qqbot.presentation.renderer import AnimeCardRenderer
from anime_qqbot.presentation.text import format_card_fallback

from .adapter import Reply

logger = logging.getLogger(__name__)


class CardReplyFactory:
    def __init__(
        self,
        *,
        assembler: CardDataAssembler,
        poster_locator: Callable[[UUID], Path | None],
        renderer: AnimeCardRenderer,
    ) -> None:
        self._assembler = assembler
        self._poster_locator = poster_locator
        self._renderer = renderer

    async def build(
        self,
        *,
        scene: CardScene,
        anime_id: UUID,
        ctx: ChatContext,
        fallback: Reply,
        now: datetime,
    ) -> Reply:
        if not card_scene_allows_image(scene):
            return fallback
        try:
            data = await self._assembler.assemble(
                anime_id,
                timezone=ctx.timezone,
                now=now,
            )
            if data is None:
                return fallback
            text_fallback = Reply.from_text(format_card_fallback(data))
            poster_path = self._poster_locator(anime_id)
            if poster_path is None:
                return text_fallback
            rendered = await self._renderer.render_cached(data, poster_path)
            if not rendered.succeeded or rendered.path is None:
                return text_fallback
            hint = (
                f"追番时发送「追番 {data.display_title}」"
                if scene in {CardScene.UNIQUE_SEARCH, CardScene.DETAIL}
                else None
            )
            return Reply.from_image(rendered.path, hint=hint)
        except Exception as exc:
            logger.warning(
                "card_reply_factory.fallback",
                extra={
                    "anime_id": str(anime_id),
                    "error_type": type(exc).__name__,
                },
            )
            return fallback


__all__ = ["CardReplyFactory"]
