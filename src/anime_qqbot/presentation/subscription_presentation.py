"""Read-only subscription projections used by image presentation."""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.application.context import ChatContext
from anime_qqbot.persistence.models.identity import ChatGroup
from anime_qqbot.persistence.models.subscriptions_v2 import FollowSubscription


@dataclass(frozen=True)
class SubscriptionPresentation:
    """Anonymous group heat and the current viewer's follow state."""

    group_scope: str | None
    viewer_scope: str | None
    viewer_follows: bool
    group_follow_counts: Mapping[UUID, int]

    @classmethod
    def empty(cls) -> SubscriptionPresentation:
        return cls(
            group_scope=None,
            viewer_scope=None,
            viewer_follows=False,
            group_follow_counts={},
        )


class SubscriptionPresentationReader:
    """Batch-read display-only subscription facts for one chat context."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def read(
        self,
        *,
        ctx: ChatContext,
        anime_ids: Collection[UUID],
        include_viewer_state: bool,
    ) -> SubscriptionPresentation:
        unique_anime_ids = tuple(dict.fromkeys(anime_ids))
        if not unique_anime_ids:
            return SubscriptionPresentation.empty()
        async with self._session_factory() as session:
            chat_group_id = await self._chat_group_id(session, ctx)
            if chat_group_id is None:
                return SubscriptionPresentation.empty()
            counts = await self._group_follow_counts(session, chat_group_id, unique_anime_ids)
            follows = (
                await self._viewer_follows(session, chat_group_id, ctx.user_id, unique_anime_ids)
                if include_viewer_state
                else set()
            )
        return SubscriptionPresentation(
            group_scope=_scope("group", ctx.platform, ctx.group_id),
            viewer_scope=(
                _scope("viewer", ctx.platform, ctx.group_id, ctx.user_id)
                if include_viewer_state
                else None
            ),
            viewer_follows=bool(follows),
            group_follow_counts=counts,
        )

    @staticmethod
    async def _chat_group_id(session: AsyncSession, ctx: ChatContext) -> UUID | None:
        stmt = select(ChatGroup.id).where(
            ChatGroup.platform == ctx.platform,
            ChatGroup.external_group_id == ctx.group_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def _group_follow_counts(
        session: AsyncSession,
        chat_group_id: UUID,
        anime_ids: tuple[UUID, ...],
    ) -> dict[UUID, int]:
        stmt = (
            select(
                FollowSubscription.anime_id,
                func.count(func.distinct(FollowSubscription.external_user_id)),
            )
            .where(FollowSubscription.chat_group_id == chat_group_id)
            .where(FollowSubscription.anime_id.in_(anime_ids))
            .group_by(FollowSubscription.anime_id)
        )
        return {anime_id: int(count) for anime_id, count in (await session.execute(stmt)).all()}

    @staticmethod
    async def _viewer_follows(
        session: AsyncSession,
        chat_group_id: UUID,
        external_user_id: str,
        anime_ids: tuple[UUID, ...],
    ) -> set[UUID]:
        stmt = select(FollowSubscription.anime_id).where(
            FollowSubscription.chat_group_id == chat_group_id,
            FollowSubscription.external_user_id == external_user_id,
            FollowSubscription.anime_id.in_(anime_ids),
        )
        return set((await session.execute(stmt)).scalars())


def _scope(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()


__all__ = ["SubscriptionPresentation", "SubscriptionPresentationReader"]
