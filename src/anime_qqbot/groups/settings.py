"""Intent-level access to per-group runtime policy."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from anime_qqbot.persistence.models.identity import ChatGroup
from anime_qqbot.persistence.models.interaction import GroupRuntimeSetting


class PolicyVersionConflictError(RuntimeError):
    """The policy changed after the caller read it."""


@dataclass(frozen=True)
class GroupRuntimePolicy:
    chat_group_id: UUID
    timezone: str
    group_enabled: bool
    general_chat_enabled: bool = False
    mention_enabled: bool = True
    direct_shortcuts_enabled: bool = False
    active_notifications_enabled: bool = True
    weekly_report_enabled: bool = False
    weekly_report_weekday: int = 0
    weekly_report_minute: int = 20 * 60
    daily_digest_enabled: bool = False
    daily_digest_at_all_enabled: bool = False
    daily_digest_anchor_minute: int = 22 * 60 + 30
    daily_digest_quiet_minutes: int = 20
    daily_digest_cutoff_minute: int = 23 * 60 + 30
    quiet_start_minute: int | None = None
    quiet_end_minute: int | None = None
    group_interval_seconds: float | None = None
    proactive_interval_seconds: float | None = None
    paused: bool = False
    pause_reason: str | None = None
    version: int = 1

    @property
    def passive_enabled(self) -> bool:
        return self.group_enabled and not self.paused

    @property
    def proactive_enabled(self) -> bool:
        return self.group_enabled and not self.paused and self.active_notifications_enabled

    def is_quiet_at(self, instant: datetime) -> bool:
        if self.quiet_start_minute is None or self.quiet_end_minute is None:
            return False
        local = instant.astimezone(ZoneInfo(self.timezone))
        minute = local.hour * 60 + local.minute
        start = self.quiet_start_minute
        end = self.quiet_end_minute
        if start == end:
            return True
        if start < end:
            return start <= minute < end
        return minute >= start or minute < end


class GroupRuntimeSettingsRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_policy(self, chat_group_id: UUID) -> GroupRuntimePolicy:
        async with self._session_factory() as session:
            group = await session.get(ChatGroup, chat_group_id)
            if group is None:
                raise LookupError(f"unknown chat group: {chat_group_id}")
            setting = await session.get(GroupRuntimeSetting, chat_group_id)
            return _policy(group, setting)

    async def update_policy(
        self,
        chat_group_id: UUID,
        *,
        expected_version: int,
        now: datetime,
        general_chat_enabled: bool | None = None,
        mention_enabled: bool | None = None,
        direct_shortcuts_enabled: bool | None = None,
        active_notifications_enabled: bool | None = None,
        weekly_report_enabled: bool | None = None,
        weekly_report_weekday: int | None = None,
        weekly_report_minute: int | None = None,
        daily_digest_enabled: bool | None = None,
        daily_digest_at_all_enabled: bool | None = None,
        daily_digest_anchor_minute: int | None = None,
        daily_digest_quiet_minutes: int | None = None,
        daily_digest_cutoff_minute: int | None = None,
        quiet_start_minute: int | None = None,
        quiet_end_minute: int | None = None,
        clear_quiet_hours: bool = False,
        group_interval_seconds: float | None = None,
        proactive_interval_seconds: float | None = None,
    ) -> GroupRuntimePolicy:
        current = await self.get_policy(chat_group_id)
        desired = replace(
            current,
            general_chat_enabled=(
                general_chat_enabled
                if general_chat_enabled is not None
                else current.general_chat_enabled
            ),
            mention_enabled=(
                mention_enabled if mention_enabled is not None else current.mention_enabled
            ),
            direct_shortcuts_enabled=(
                direct_shortcuts_enabled
                if direct_shortcuts_enabled is not None
                else current.direct_shortcuts_enabled
            ),
            active_notifications_enabled=(
                active_notifications_enabled
                if active_notifications_enabled is not None
                else current.active_notifications_enabled
            ),
            weekly_report_enabled=(
                weekly_report_enabled
                if weekly_report_enabled is not None
                else current.weekly_report_enabled
            ),
            weekly_report_weekday=(
                weekly_report_weekday
                if weekly_report_weekday is not None
                else current.weekly_report_weekday
            ),
            weekly_report_minute=(
                weekly_report_minute
                if weekly_report_minute is not None
                else current.weekly_report_minute
            ),
            daily_digest_enabled=(
                daily_digest_enabled
                if daily_digest_enabled is not None
                else current.daily_digest_enabled
            ),
            daily_digest_at_all_enabled=(
                daily_digest_at_all_enabled
                if daily_digest_at_all_enabled is not None
                else current.daily_digest_at_all_enabled
            ),
            daily_digest_anchor_minute=(
                daily_digest_anchor_minute
                if daily_digest_anchor_minute is not None
                else current.daily_digest_anchor_minute
            ),
            daily_digest_quiet_minutes=(
                daily_digest_quiet_minutes
                if daily_digest_quiet_minutes is not None
                else current.daily_digest_quiet_minutes
            ),
            daily_digest_cutoff_minute=(
                daily_digest_cutoff_minute
                if daily_digest_cutoff_minute is not None
                else current.daily_digest_cutoff_minute
            ),
            group_interval_seconds=(
                group_interval_seconds
                if group_interval_seconds is not None
                else current.group_interval_seconds
            ),
            proactive_interval_seconds=(
                proactive_interval_seconds
                if proactive_interval_seconds is not None
                else current.proactive_interval_seconds
            ),
        )
        if clear_quiet_hours:
            desired = replace(desired, quiet_start_minute=None, quiet_end_minute=None)
        elif quiet_start_minute is not None or quiet_end_minute is not None:
            if quiet_start_minute is None or quiet_end_minute is None:
                raise ValueError("quiet hours require both start and end")
            desired = replace(
                desired,
                quiet_start_minute=quiet_start_minute,
                quiet_end_minute=quiet_end_minute,
            )
        return await self._write(
            desired,
            expected_version=expected_version,
            now=now,
        )

    async def pause_group(
        self,
        chat_group_id: UUID,
        *,
        reason: str,
        expected_version: int,
        now: datetime,
    ) -> GroupRuntimePolicy:
        current = await self.get_policy(chat_group_id)
        return await self._write(
            replace(current, paused=True, pause_reason=reason[:256]),
            expected_version=expected_version,
            now=now,
        )

    async def resume_group(
        self,
        chat_group_id: UUID,
        *,
        expected_version: int,
        now: datetime,
    ) -> GroupRuntimePolicy:
        current = await self.get_policy(chat_group_id)
        return await self._write(
            replace(current, paused=False, pause_reason=None),
            expected_version=expected_version,
            now=now,
        )

    async def _write(
        self,
        desired: GroupRuntimePolicy,
        *,
        expected_version: int,
        now: datetime,
    ) -> GroupRuntimePolicy:
        if expected_version != desired.version:
            raise PolicyVersionConflictError("group policy version changed")
        values = _setting_values(desired, now=now, version=expected_version + 1)
        async with self._session_factory() as session:
            existing = await session.get(GroupRuntimeSetting, desired.chat_group_id)
            if existing is None:
                if expected_version != 1:
                    raise PolicyVersionConflictError("group policy version changed")
                session.add(GroupRuntimeSetting(**values))
            else:
                stmt = (
                    update(GroupRuntimeSetting)
                    .where(
                        GroupRuntimeSetting.chat_group_id == desired.chat_group_id,
                        GroupRuntimeSetting.version == expected_version,
                    )
                    .values(**values)
                )
                result = await session.execute(stmt)
                if int(getattr(result, "rowcount", 0)) != 1:
                    raise PolicyVersionConflictError("group policy version changed")
            await session.commit()
        return replace(desired, version=expected_version + 1)

    async def list_policies(self) -> list[GroupRuntimePolicy]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(ChatGroup, GroupRuntimeSetting).outerjoin(
                        GroupRuntimeSetting,
                        GroupRuntimeSetting.chat_group_id == ChatGroup.id,
                    )
                )
            ).all()
            return [_policy(group, setting) for group, setting in rows]


def _policy(group: ChatGroup, setting: GroupRuntimeSetting | None) -> GroupRuntimePolicy:
    if setting is None:
        return GroupRuntimePolicy(
            chat_group_id=group.id,
            timezone=group.timezone,
            group_enabled=group.enabled,
        )
    return GroupRuntimePolicy(
        chat_group_id=group.id,
        timezone=group.timezone,
        group_enabled=group.enabled,
        general_chat_enabled=setting.general_chat_enabled,
        mention_enabled=setting.mention_enabled,
        direct_shortcuts_enabled=setting.direct_shortcuts_enabled,
        active_notifications_enabled=setting.active_notifications_enabled,
        weekly_report_enabled=setting.weekly_report_enabled,
        weekly_report_weekday=setting.weekly_report_weekday,
        weekly_report_minute=setting.weekly_report_minute,
        daily_digest_enabled=setting.daily_digest_enabled,
        daily_digest_at_all_enabled=setting.daily_digest_at_all_enabled,
        daily_digest_anchor_minute=setting.daily_digest_anchor_minute,
        daily_digest_quiet_minutes=setting.daily_digest_quiet_minutes,
        daily_digest_cutoff_minute=setting.daily_digest_cutoff_minute,
        quiet_start_minute=setting.quiet_start_minute,
        quiet_end_minute=setting.quiet_end_minute,
        group_interval_seconds=setting.group_interval_seconds,
        proactive_interval_seconds=setting.proactive_interval_seconds,
        paused=setting.paused,
        pause_reason=setting.pause_reason,
        version=setting.version,
    )


def _setting_values(
    policy: GroupRuntimePolicy, *, now: datetime, version: int
) -> dict[str, object]:
    return {
        "chat_group_id": policy.chat_group_id,
        "general_chat_enabled": policy.general_chat_enabled,
        "mention_enabled": policy.mention_enabled,
        "direct_shortcuts_enabled": policy.direct_shortcuts_enabled,
        "active_notifications_enabled": policy.active_notifications_enabled,
        "weekly_report_enabled": policy.weekly_report_enabled,
        "weekly_report_weekday": policy.weekly_report_weekday,
        "weekly_report_minute": policy.weekly_report_minute,
        "daily_digest_enabled": policy.daily_digest_enabled,
        "daily_digest_at_all_enabled": policy.daily_digest_at_all_enabled,
        "daily_digest_anchor_minute": policy.daily_digest_anchor_minute,
        "daily_digest_quiet_minutes": policy.daily_digest_quiet_minutes,
        "daily_digest_cutoff_minute": policy.daily_digest_cutoff_minute,
        "quiet_start_minute": policy.quiet_start_minute,
        "quiet_end_minute": policy.quiet_end_minute,
        "group_interval_seconds": policy.group_interval_seconds,
        "proactive_interval_seconds": policy.proactive_interval_seconds,
        "paused": policy.paused,
        "pause_reason": policy.pause_reason,
        "version": version,
        "updated_at": now,
    }


__all__ = [
    "GroupRuntimePolicy",
    "GroupRuntimeSettingsRepository",
    "PolicyVersionConflictError",
]
