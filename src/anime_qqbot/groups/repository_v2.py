"""Chat group repository (Task 7).

Maintains chat_groups and group_memberships in the v0.2 schema.

Semantics:
* `upsert_group_event` is called on every group message. It creates
  the chat_groups row on first contact, refreshes the AstrBot
  unified_msg_origin (UMO), bumps umo_refreshed_at to now, and
  upserts the membership row (display name and last_seen_at).
* UMO is treated as an opaque AstrBot routing token. We never parse it,
  we never re-derive it from group_id; if the value we receive is
  older than what we already have, we keep the newer one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.persistence.models.identity import (
    ChatGroup,
    GroupMembership,
)


@dataclass(frozen=True)
class ChatGroupRow:
    id: UUID
    platform: str
    external_group_id: str
    unified_msg_origin: str | None
    umo_refreshed_at: datetime | None
    enabled: bool


@dataclass(frozen=True)
class GroupEvent:
    platform: str
    external_group_id: str
    external_user_id: str
    display_name: str
    unified_msg_origin: str | None
    timestamp: datetime


class ChatGroupRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert_group_event(self, event: GroupEvent) -> ChatGroupRow:
        if not event.external_group_id.strip():
            raise ValueError("external_group_id must not be empty")
        if not event.external_user_id.strip():
            raise ValueError("external_user_id must not be empty")
        async with self._session_factory() as session:
            group = await self._upsert_group(session, event)
            await self._upsert_membership(session, group, event)
            await session.commit()
            await session.refresh(group)
            return _to_row(group)

    async def find_by_external(self, platform: str, external_group_id: str) -> ChatGroupRow | None:
        async with self._session_factory() as session:
            stmt = select(ChatGroup).where(
                ChatGroup.platform == platform,
                ChatGroup.external_group_id == external_group_id,
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            return _to_row(row) if row is not None else None

    # -- helpers ----------------------------------------------------------

    async def _upsert_group(self, session: AsyncSession, event: GroupEvent) -> ChatGroup:
        existing = await self._find_group(session, event.platform, event.external_group_id)
        if existing is None:
            stmt = (
                pg_insert(ChatGroup)
                .values(
                    id=uuid4(),
                    platform=event.platform,
                    external_group_id=event.external_group_id,
                    unified_msg_origin=event.unified_msg_origin,
                    umo_refreshed_at=event.timestamp if event.unified_msg_origin else None,
                    timezone="Asia/Shanghai",
                    enabled=True,
                    created_at=event.timestamp,
                    updated_at=event.timestamp,
                )
                .on_conflict_do_nothing(
                    index_elements=["platform", "external_group_id"],
                )
                .returning(ChatGroup.id)
            )
            result = await session.execute(stmt)
            inserted = result.scalar_one_or_none()
            if inserted is not None:
                row = await session.get(ChatGroup, inserted)
                assert row is not None
                return row
            # Another transaction inserted the row between our SELECT and
            # INSERT — fall through to the update path.
            existing = await self._find_group(session, event.platform, event.external_group_id)
            assert existing is not None

        existing.updated_at = event.timestamp
        if event.unified_msg_origin and (
            existing.umo_refreshed_at is None or event.timestamp >= existing.umo_refreshed_at
        ):
            existing.unified_msg_origin = event.unified_msg_origin
            existing.umo_refreshed_at = event.timestamp
        return existing

    async def _upsert_membership(
        self,
        session: AsyncSession,
        group: ChatGroup,
        event: GroupEvent,
    ) -> None:
        stmt = (
            pg_insert(GroupMembership)
            .values(
                id=uuid4(),
                chat_group_id=group.id,
                external_user_id=event.external_user_id,
                display_name=event.display_name,
                role="member",
                last_seen_at=event.timestamp,
            )
            .on_conflict_do_update(
                index_elements=["chat_group_id", "external_user_id"],
                set_={"display_name": event.display_name, "last_seen_at": event.timestamp},
            )
        )
        await session.execute(stmt)

    @staticmethod
    async def _find_group(
        session: AsyncSession, platform: str, external_group_id: str
    ) -> ChatGroup | None:
        stmt = select(ChatGroup).where(
            ChatGroup.platform == platform,
            ChatGroup.external_group_id == external_group_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none()


def _to_row(group: ChatGroup) -> ChatGroupRow:
    return ChatGroupRow(
        id=group.id,
        platform=group.platform,
        external_group_id=group.external_group_id,
        unified_msg_origin=group.unified_msg_origin,
        umo_refreshed_at=group.umo_refreshed_at,
        enabled=group.enabled,
    )


def utcnow() -> datetime:
    return datetime.now(UTC)


__all__ = ["ChatGroupRepository", "ChatGroupRow", "GroupEvent", "utcnow"]
