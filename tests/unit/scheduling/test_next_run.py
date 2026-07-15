from datetime import UTC, datetime, time

from anime_qqbot.scheduling.module import ScheduleSpec, ScheduleType, next_run


def test_daily_next_run_is_saved_as_utc() -> None:
    spec = ScheduleSpec(ScheduleType.DAILY, "Asia/Shanghai", time(9, 0))
    assert next_run(spec, datetime(2026, 7, 15, 2, tzinfo=UTC)) == datetime(
        2026, 7, 16, 1, tzinfo=UTC
    )


def test_weekly_next_run_crosses_week_boundary() -> None:
    spec = ScheduleSpec(ScheduleType.WEEKLY, "Asia/Shanghai", time(9), weekday=0)
    assert next_run(spec, datetime(2026, 7, 13, 2, tzinfo=UTC)) == datetime(
        2026, 7, 20, 1, tzinfo=UTC
    )
