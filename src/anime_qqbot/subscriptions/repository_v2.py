"""v0.2 follow subscription store (Task 17)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.persistence.models.catalog import Anime


@dataclass(frozen=True)
class FollowRow:
    id: UUID
    chat_group_id: UUID
    external_user_id: str
    anime_id: UUID
    notify_airing: bool
    notify_resource: bool


class FollowRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def subscribe(
        self,
        *,
        chat_group_id: UUID,
        external_user_id: str,
        anime_id: UUID,
    ) -> FollowRow:
        async with self._session_factory() as session:
            # Ensure anime exists and is not disabled/nsfw=true
            anime = await session.get(Anime, anime_id)
            if anime is None or anime.disabled:
                raise LookupError(f"anime {anime_id} not found or disabled")
            if anime.nsfw_flag == "true":
                raise LookupError(f"anime {anime_id} is blocked")

            from anime_qqbot.persistence.models.subscriptions_v2 import (
                FollowSubscription,
            )

            stmt = (
                pg_insert(FollowSubscription)
                .values(
                    id=uuid4(),
                    chat_group_id=chat_group_id,
                    external_user_id=external_user_id,
                    anime_id=anime_id,
                    notify_airing=True,
                    notify_resource=True,
                    created_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(
                    index_elements=["chat_group_id", "external_user_id", "anime_id"],
                )
                .returning(FollowSubscription.id)
            )
            result = await session.execute(stmt)
            inserted = result.scalar_one_or_none()
            if inserted is not None:
                await session.commit()
                return FollowRow(inserted, chat_group_id, external_user_id, anime_id, True, True)
            await session.rollback()
            existing = await self._find(session, chat_group_id, external_user_id, anime_id)
            assert existing is not None
            return FollowRow(
                existing.id,
                existing.chat_group_id or UUID(int=0),
                existing.external_user_id or "",
                existing.anime_id or UUID(int=0),
                existing.notify_airing,
                existing.notify_resource,
            )

    async def unsubscribe(
        self, *, chat_group_id: UUID, external_user_id: str, anime_id: UUID
    ) -> None:
        async with self._session_factory() as session:
            row = await self._find(session, chat_group_id, external_user_id, anime_id)
            if row is not None:
                await session.delete(row)
                await session.commit()

    async def list_for_user(self, *, chat_group_id: UUID, external_user_id: str) -> list[FollowRow]:
        async with self._session_factory() as session:
            from anime_qqbot.persistence.models.subscriptions_v2 import (
                FollowSubscription,
            )

            stmt = select(FollowSubscription).where(
                FollowSubscription.chat_group_id == chat_group_id,
                FollowSubscription.external_user_id == external_user_id,
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [
                FollowRow(
                    r.id,
                    r.chat_group_id,
                    r.external_user_id,
                    r.anime_id,
                    r.notify_airing,
                    r.notify_resource,
                )
                for r in rows
            ]

    async def active_subscribers_for_anime(self, anime_id: UUID) -> list[FollowRow]:
        async with self._session_factory() as session:
            from anime_qqbot.persistence.models.subscriptions_v2 import (
                FollowSubscription,
            )

            stmt = select(FollowSubscription).where(
                FollowSubscription.anime_id == anime_id,
                FollowSubscription.notify_airing.is_(True),
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [
                FollowRow(
                    r.id,
                    r.chat_group_id,
                    r.external_user_id,
                    r.anime_id,
                    r.notify_airing,
                    r.notify_resource,
                )
                for r in rows
            ]

    @staticmethod
    async def _find(
        session: AsyncSession, chat_group_id: UUID, external_user_id: str, anime_id: UUID
    ) -> Any:
        from anime_qqbot.persistence.models.subscriptions_v2 import (
            FollowSubscription,
        )

        stmt = select(FollowSubscription).where(
            FollowSubscription.chat_group_id == chat_group_id,
            FollowSubscription.external_user_id == external_user_id,
            FollowSubscription.anime_id == anime_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none()


__all__ = ["FollowRepository", "FollowRow"]
