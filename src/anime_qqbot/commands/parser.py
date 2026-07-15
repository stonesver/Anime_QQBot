import re
from datetime import date
from typing import ClassVar

from anime_qqbot.commands.models import CommandIntent, CommandKind


class CommandParser:
    _simple: ClassVar[dict[str, CommandKind]] = {
        "本周番剧": CommandKind.WEEK,
        "周番表": CommandKind.WEEK,
        "我的订阅": CommandKind.MY_SUBSCRIPTIONS,
        "关闭每日推送": CommandKind.DISABLE_DAILY,
        "关闭每周推送": CommandKind.DISABLE_WEEKLY,
        "推送状态": CommandKind.PUSH_STATUS,
        "立即推送今日番剧": CommandKind.PUSH_TODAY_NOW,
        "帮助": CommandKind.HELP,
        "help": CommandKind.HELP,
    }
    _with_argument: ClassVar[tuple[tuple[str, CommandKind], ...]] = (
        ("下次更新", CommandKind.NEXT_AIRING),
        ("取消订阅", CommandKind.UNSUBSCRIBE),
        ("今日番剧", CommandKind.TODAY),
        ("季度番剧", CommandKind.SEASON),
        ("开启每日推送", CommandKind.ENABLE_DAILY),
        ("开启每周推送", CommandKind.ENABLE_WEEKLY),
        ("设置时区", CommandKind.SET_TIMEZONE),
        ("搜索", CommandKind.SEARCH),
        ("番剧", CommandKind.DETAIL),
        ("订阅", CommandKind.SUBSCRIBE),
    )

    def parse(self, content: str) -> CommandIntent:
        normalized = re.sub(r"\s+", " ", content.strip())
        if normalized in self._simple:
            return CommandIntent(self._simple[normalized])
        for prefix, kind in self._with_argument:
            if normalized == prefix:
                if kind is CommandKind.TODAY:
                    return CommandIntent(kind)
                if kind is CommandKind.SEASON:
                    return CommandIntent(kind)
                return self._invalid(kind, f"{prefix} 缺少参数")
            if normalized.startswith(f"{prefix} "):
                arguments = tuple(normalized[len(prefix) + 1 :].split(" "))
                return self._validate(kind, arguments)
        return CommandIntent(CommandKind.HELP, error="未识别命令")

    def _validate(self, kind: CommandKind, arguments: tuple[str, ...]) -> CommandIntent:
        if kind is CommandKind.TODAY:
            if len(arguments) != 1 or not self._is_date(arguments[0]):
                return self._invalid(kind, "日期格式应为 YYYY-MM-DD")
        elif kind is CommandKind.SEASON:
            if len(arguments) not in {1, 2}:
                return self._invalid(kind, "季度格式应为 [年份] 春|夏|秋|冬")
            season = arguments[-1]
            if season not in {"春", "夏", "秋", "冬"}:
                return self._invalid(kind, "季度只能是春、夏、秋、冬")
            if len(arguments) == 2 and not arguments[0].isdigit():
                return self._invalid(kind, "年份必须是数字")
        elif kind is CommandKind.ENABLE_DAILY:
            if len(arguments) != 1 or not self._is_time(arguments[0]):
                return self._invalid(kind, "时间格式应为 HH:mm")
        elif kind is CommandKind.ENABLE_WEEKLY:
            if (
                len(arguments) != 2
                or arguments[0] not in {"一", "二", "三", "四", "五", "六", "日", "天"}
                or not self._is_time(arguments[1])
            ):
                return self._invalid(kind, "格式应为 开启每周推送 <星期> <HH:mm>")
        return CommandIntent(kind, arguments)

    @staticmethod
    def _is_date(value: str) -> bool:
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
        return True

    @staticmethod
    def _is_time(value: str) -> bool:
        match = re.fullmatch(r"(\d{2}):(\d{2})", value)
        return bool(match and int(match.group(1)) < 24 and int(match.group(2)) < 60)

    @staticmethod
    def _invalid(kind: CommandKind, message: str) -> CommandIntent:
        return CommandIntent(kind, valid=False, error=message)
