# ruff: noqa: RUF001

from datetime import datetime, time
from typing import ClassVar
from zoneinfo import ZoneInfo

from anime_qqbot.commands.models import CommandIntent, CommandKind
from anime_qqbot.groups.permissions import PermissionPolicy
from anime_qqbot.groups.repository import GroupRepository
from anime_qqbot.qq.contracts import OutboundMessage, QQEvent
from anime_qqbot.scheduling.module import ScheduleSpec, ScheduleType
from anime_qqbot.scheduling.repository import ScheduleRepository


class ScheduleAdminService:
    _weekdays: ClassVar[dict[str, int]] = {
        "一": 0,
        "二": 1,
        "三": 2,
        "四": 3,
        "五": 4,
        "六": 5,
        "日": 6,
        "天": 6,
    }

    def __init__(
        self,
        groups: GroupRepository,
        schedules: ScheduleRepository,
        permissions: PermissionPolicy,
    ) -> None:
        self._groups = groups
        self._schedules = schedules
        self._permissions = permissions

    async def handle(self, event: QQEvent, intent: CommandIntent, now: datetime) -> OutboundMessage:
        if not self._permissions.can_manage_group(event):
            return OutboundMessage("只有群主、管理员或引导管理员可以修改推送设置。")
        if not event.group_openid or not event.member_openid:
            return OutboundMessage("该命令只能在群聊中使用。")
        group = await self._groups.find_group(event.group_openid)
        if group is None:
            return OutboundMessage("群信息尚未初始化，请重新 @机器人。")
        if intent.kind is CommandKind.ENABLE_DAILY:
            await self._schedules.configure(
                group.id,
                ScheduleSpec(
                    ScheduleType.DAILY, group.timezone, time.fromisoformat(intent.arguments[0])
                ),
                now,
            )
            return OutboundMessage("每日推送已开启。")
        if intent.kind is CommandKind.ENABLE_WEEKLY:
            await self._schedules.configure(
                group.id,
                ScheduleSpec(
                    ScheduleType.WEEKLY,
                    group.timezone,
                    time.fromisoformat(intent.arguments[1]),
                    self._weekdays[intent.arguments[0]],
                ),
                now,
            )
            return OutboundMessage("每周推送已开启。")
        if intent.kind in {CommandKind.DISABLE_DAILY, CommandKind.DISABLE_WEEKLY}:
            kind = "daily" if intent.kind is CommandKind.DISABLE_DAILY else "weekly"
            await self._schedules.disable(group.id, kind)
            return OutboundMessage("推送计划已关闭。")
        if intent.kind is CommandKind.SET_TIMEZONE:
            try:
                ZoneInfo(intent.arguments[0])
            except (KeyError, ValueError):
                return OutboundMessage("无效的 IANA 时区。")
            await self._groups.set_timezone(group.id, intent.arguments[0])
            return OutboundMessage(f"时区已设置为 {intent.arguments[0]}。")
        if intent.kind is CommandKind.PUSH_STATUS:
            rows = await self._schedules.list_for_group(group.id)
            if not rows:
                return OutboundMessage(f"时区: {group.timezone}\n暂无推送计划。")
            lines = [f"时区: {group.timezone}"] + [
                (
                    f"{row.schedule_type}: {'开启' if row.enabled else '关闭'}，"
                    f"下次 {row.next_run_at.isoformat()}"
                )
                for row in rows
            ]
            return OutboundMessage("\n".join(lines))
        if intent.kind is CommandKind.PUSH_TODAY_NOW:
            created = await self._schedules.create_job(
                group.id,
                "manual_daily",
                event.event_id,
                now,
                {"group_openid": event.group_openid, "text": "管理员手动触发今日番剧推送。"},
            )
            return OutboundMessage("已创建手动推送任务。" if created else "该手动任务已存在。")
        if intent.kind is CommandKind.REDELIVER:
            created = await self._schedules.redeliver_unknown(
                int(intent.arguments[0]),
                group.id,
                event.member_openid,
                event.event_id,
                now,
            )
            return OutboundMessage(
                "已创建明确补发任务。" if created else "未找到可补发的 unknown 任务。"
            )
        return OutboundMessage("不支持的推送命令。")
