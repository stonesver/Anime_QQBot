from dataclasses import dataclass
from enum import StrEnum


class CommandKind(StrEnum):
    TODAY = "today"
    WEEK = "week"
    SEASON = "season"
    SEARCH = "search"
    DETAIL = "detail"
    NEXT_AIRING = "next_airing"
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    MY_SUBSCRIPTIONS = "my_subscriptions"
    ENABLE_DAILY = "enable_daily"
    DISABLE_DAILY = "disable_daily"
    ENABLE_WEEKLY = "enable_weekly"
    DISABLE_WEEKLY = "disable_weekly"
    SET_TIMEZONE = "set_timezone"
    PUSH_STATUS = "push_status"
    PUSH_TODAY_NOW = "push_today_now"
    REDELIVER = "redeliver"
    HELP = "help"


@dataclass(frozen=True)
class CommandIntent:
    kind: CommandKind
    arguments: tuple[str, ...] = ()
    valid: bool = True
    error: str | None = None
