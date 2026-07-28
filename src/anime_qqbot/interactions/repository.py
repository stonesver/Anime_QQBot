from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.interactions.models import CandidateItem, InteractionScope, SessionView
from anime_qqbot.persistence.models.interaction import InteractionSession


class InteractionSessionRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        ttl: timedelta = timedelta(minutes=5),
    ) -> None:
        self._session_factory = session_factory
        self._ttl = ttl

    async def replace(
        self,
        scope: InteractionScope,
        candidates: list[CandidateItem],
        *,
        now: datetime,
        result_message_id: str | None = None,
    ) -> SessionView:
        if not candidates:
            raise ValueError("interaction session requires at least one candidate")
        row_id = uuid4()
        expires_at = now + self._ttl
        payload = [
            {
                "anime_id": str(item.anime_id),
                "title": item.title[:160],
                "subtitle": item.subtitle[:160] if item.subtitle else None,
            }
            for item in candidates
        ]
        stmt = (
            pg_insert(InteractionSession)
            .values(
                id=row_id,
                platform=scope.platform,
                external_group_id=scope.external_group_id,
                external_user_id=scope.external_user_id,
                candidates=payload,
                result_message_id=result_message_id,
                created_at=now,
                expires_at=expires_at,
            )
            .on_conflict_do_update(
                constraint="uq_interaction_sessions_scope",
                set_={
                    "id": row_id,
                    "candidates": payload,
                    "result_message_id": result_message_id,
                    "created_at": now,
                    "expires_at": expires_at,
                },
            )
            .returning(InteractionSession)
        )
        async with self._session_factory() as session:
            row = (await session.execute(stmt)).scalar_one()
            await session.commit()
            return _view(row)

    async def resolve(
        self,
        scope: InteractionScope,
        *,
        now: datetime,
        reply_to_message_id: str | None = None,
        require_reply_match: bool = False,
    ) -> SessionView | None:
        stmt = select(InteractionSession).where(
            InteractionSession.platform == scope.platform,
            InteractionSession.external_group_id == scope.external_group_id,
            InteractionSession.external_user_id == scope.external_user_id,
            InteractionSession.expires_at > now,
        )
        async with self._session_factory() as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            if require_reply_match and (
                not reply_to_message_id or row.result_message_id != reply_to_message_id
            ):
                return None
            return _view(row)

    async def cleanup_expired(self, *, now: datetime, limit: int = 200) -> int:
        ids = (
            select(InteractionSession.id)
            .where(InteractionSession.expires_at <= now)
            .order_by(InteractionSession.expires_at)
            .limit(limit)
        )
        async with self._session_factory() as session:
            result = await session.execute(
                delete(InteractionSession).where(InteractionSession.id.in_(ids))
            )
            await session.commit()
            return int(getattr(result, "rowcount", 0) or 0)


def _view(row: InteractionSession) -> SessionView:
    return SessionView(
        id=row.id,
        scope=InteractionScope(
            platform=row.platform,
            external_group_id=row.external_group_id,
            external_user_id=row.external_user_id,
        ),
        candidates=tuple(
            CandidateItem(
                anime_id=UUID(str(raw["anime_id"])),
                title=str(raw["title"]),
                subtitle=str(raw["subtitle"]) if raw.get("subtitle") else None,
            )
            for raw in row.candidates
        ),
        result_message_id=row.result_message_id,
        created_at=row.created_at,
        expires_at=row.expires_at,
    )


__all__ = ["InteractionSessionRepository"]
