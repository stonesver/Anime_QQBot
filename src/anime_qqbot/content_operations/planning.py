"""Pure scheduling policy for group content publications."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class DailyDigestDecision:
    period_date: date
    period_start: datetime
    period_end: datetime
    send_at: datetime | None
    due: bool


@dataclass(frozen=True, slots=True)
class DailyDigestSchedule:
    anchor_minute: int = 22 * 60 + 30
    quiet_minutes: int = 20
    cutoff_minute: int = 23 * 60 + 30

    def __post_init__(self) -> None:
        if not 0 <= self.anchor_minute < self.cutoff_minute <= 1439:
            raise ValueError("digest anchor must be before cutoff")
        if not 1 <= self.quiet_minutes <= self.cutoff_minute - self.anchor_minute:
            raise ValueError("digest quiet window does not fit before cutoff")

    def decide(
        self,
        *,
        now: datetime,
        timezone: ZoneInfo,
        latest_release_at: datetime | None,
        has_releases: bool,
    ) -> DailyDigestDecision:
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        local_now = now.astimezone(timezone)
        local_minute = local_now.hour * 60 + local_now.minute
        period_date = local_now.date()
        if local_minute > self.cutoff_minute:
            period_date += timedelta(days=1)

        period_start = self._local_at(period_date - timedelta(days=1), self.cutoff_minute, timezone)
        period_end = self._local_at(period_date, self.cutoff_minute, timezone)
        if not has_releases or latest_release_at is None:
            return DailyDigestDecision(
                period_date=period_date,
                period_start=period_start,
                period_end=period_end,
                send_at=None,
                due=False,
            )

        anchor = self._local_at(period_date, self.anchor_minute, timezone)
        quiet_at = latest_release_at.astimezone(UTC) + timedelta(minutes=self.quiet_minutes)
        send_at = min(max(anchor, quiet_at), period_end)
        return DailyDigestDecision(
            period_date=period_date,
            period_start=period_start,
            period_end=period_end,
            send_at=send_at,
            due=now.astimezone(UTC) >= send_at and now.astimezone(UTC) <= period_end,
        )

    @staticmethod
    def _local_at(day: date, minute: int, timezone: ZoneInfo) -> datetime:
        local = datetime.combine(
            day,
            time(hour=minute // 60, minute=minute % 60),
            tzinfo=timezone,
        )
        return local.astimezone(UTC)


__all__ = ["DailyDigestDecision", "DailyDigestSchedule"]
