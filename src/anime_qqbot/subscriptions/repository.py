from enum import StrEnum

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.persistence.models.identity import Group
from anime_qqbot.persistence.models.subscriptions import Subscription


class SubscriptionChange(StrEnum):
    ADDED = "added"
    RESTORED = "restored"
    UNCHANGED = "unchanged"
    DISABLED = "disabled"
    NOT_FOUND = "not_found"


class SubscriptionRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def subscribe(
        self, group_openid: str, member_openid: str, subject_id: int
    ) -> SubscriptionChange:
        async with self._sessions() as session, session.begin():
            group_id = await self._group_id(session, group_openid)
            existing = await session.scalar(
                select(Subscription)
                .where(
                    Subscription.group_id == group_id,
                    Subscription.member_openid == member_openid,
                    Subscription.subject_id == subject_id,
                )
                .with_for_update()
            )
            if existing is None:
                session.add(
                    Subscription(
                        group_id=group_id,
                        member_openid=member_openid,
                        subject_id=subject_id,
                    )
                )
                return SubscriptionChange.ADDED
            if existing.enabled:
                return SubscriptionChange.UNCHANGED
            existing.enabled = True
            return SubscriptionChange.RESTORED

    async def unsubscribe(
        self, group_openid: str, member_openid: str, subject_id: int
    ) -> SubscriptionChange:
        async with self._sessions() as session, session.begin():
            group_id = await self._group_id(session, group_openid)
            existing = await session.scalar(
                select(Subscription).where(
                    Subscription.group_id == group_id,
                    Subscription.member_openid == member_openid,
                    Subscription.subject_id == subject_id,
                )
            )
            if existing is None or not existing.enabled:
                return SubscriptionChange.NOT_FOUND
            existing.enabled = False
            return SubscriptionChange.DISABLED

    async def list_for_member(self, group_openid: str, member_openid: str) -> list[int]:
        async with self._sessions() as session:
            group_id = await self._group_id(session, group_openid)
            rows = await session.scalars(
                select(Subscription.subject_id)
                .where(
                    Subscription.group_id == group_id,
                    Subscription.member_openid == member_openid,
                    Subscription.enabled.is_(True),
                )
                .order_by(Subscription.subject_id)
            )
            return list(rows)

    async def disable_group(self, group_openid: str) -> None:
        async with self._sessions() as session, session.begin():
            group_id = await self._group_id(session, group_openid)
            await session.execute(
                update(Subscription).where(Subscription.group_id == group_id).values(enabled=False)
            )

    @staticmethod
    async def _group_id(session: AsyncSession, group_openid: str) -> int:
        group_id = await session.scalar(select(Group.id).where(Group.group_openid == group_openid))
        if group_id is None:
            raise LookupError("group is not registered")
        return group_id
