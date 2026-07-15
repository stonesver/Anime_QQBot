from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.persistence.models.identity import Group, GroupMember
from anime_qqbot.persistence.models.runtime import ProcessedEvent
from anime_qqbot.qq.contracts import QQEvent, QQEventType


class GroupRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def observe(self, event: QQEvent) -> int | None:
        if not event.group_openid:
            return None
        async with self._sessions() as session, session.begin():
            values: dict[str, object] = {"group_openid": event.group_openid}
            updates: dict[str, object] = {"is_active": True}
            if event.event_type is QQEventType.GROUP_REMOVED:
                updates["is_active"] = False
            elif event.event_type is QQEventType.ACTIVE_MESSAGES_ENABLED:
                updates["active_messages_enabled"] = True
            elif event.event_type is QQEventType.ACTIVE_MESSAGES_DISABLED:
                updates["active_messages_enabled"] = False
            statement = (
                insert(Group)
                .values(**values, **updates)
                .on_conflict_do_update(index_elements=[Group.group_openid], set_=updates)
                .returning(Group.id)
            )
            group_id = (await session.execute(statement)).scalar_one()
            if event.member_openid:
                member_values = {
                    "group_id": group_id,
                    "member_openid": event.member_openid,
                    "role": event.member_role.value,
                    "is_active": event.event_type is not QQEventType.GROUP_REMOVED,
                }
                member = insert(GroupMember).values(**member_values)
                await session.execute(
                    member.on_conflict_do_update(
                        constraint="uq_group_members_group_member",
                        set_={
                            "role": event.member_role.value,
                            "is_active": event.event_type is not QQEventType.GROUP_REMOVED,
                        },
                    )
                )
            return group_id

    async def claim_event(self, event: QQEvent) -> bool:
        async with self._sessions() as session, session.begin():
            statement = (
                insert(ProcessedEvent)
                .values(platform_event_id=event.event_id, event_type=event.event_type.value)
                .on_conflict_do_nothing()
                .returning(ProcessedEvent.platform_event_id)
            )
            return (await session.execute(statement)).scalar_one_or_none() is not None

    async def find_group(self, group_openid: str) -> Group | None:
        async with self._sessions() as session:
            result = await session.scalar(select(Group).where(Group.group_openid == group_openid))
            return result

    async def set_timezone(self, group_id: int, timezone: str) -> None:
        async with self._sessions() as session, session.begin():
            await session.execute(
                update(Group).where(Group.id == group_id).values(timezone=timezone)
            )
