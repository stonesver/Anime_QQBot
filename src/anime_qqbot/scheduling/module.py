from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo


class ScheduleType(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"


@dataclass(frozen=True)
class ScheduleSpec:
    schedule_type: ScheduleType
    timezone: str
    local_time: time
    weekday: int | None = None

    def __post_init__(self) -> None:
        ZoneInfo(self.timezone)
        if self.schedule_type is ScheduleType.WEEKLY and self.weekday not in range(7):
            raise ValueError("weekly schedule requires weekday 0..6")


def next_run(spec: ScheduleSpec, after: datetime) -> datetime:
    if after.tzinfo is None:
        raise ValueError("after must be timezone-aware")
    timezone = ZoneInfo(spec.timezone)
    local_after = after.astimezone(timezone)
    candidate = datetime.combine(local_after.date(), spec.local_time, timezone)
    if spec.schedule_type is ScheduleType.WEEKLY:
        assert spec.weekday is not None
        candidate += timedelta(days=(spec.weekday - candidate.weekday()) % 7)
    if candidate <= local_after:
        candidate += timedelta(days=1 if spec.schedule_type is ScheduleType.DAILY else 7)
    return candidate.astimezone(UTC)
