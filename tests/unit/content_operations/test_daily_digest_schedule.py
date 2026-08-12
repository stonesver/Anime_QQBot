from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from anime_qqbot.content_operations.planning import DailyDigestSchedule

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_digest_waits_for_quiet_window_after_late_release() -> None:
    schedule = DailyDigestSchedule()

    decision = schedule.decide(
        now=datetime(2026, 8, 11, 14, 35, tzinfo=UTC),  # 22:35 Shanghai
        timezone=SHANGHAI,
        latest_release_at=datetime(2026, 8, 11, 14, 25, tzinfo=UTC),
        has_releases=True,
    )

    assert decision.period_date == date(2026, 8, 11)
    assert decision.due is False
    assert decision.send_at == datetime(2026, 8, 11, 14, 45, tzinfo=UTC)


def test_digest_sends_at_anchor_when_release_is_already_quiet() -> None:
    schedule = DailyDigestSchedule()

    decision = schedule.decide(
        now=datetime(2026, 8, 11, 14, 30, tzinfo=UTC),
        timezone=SHANGHAI,
        latest_release_at=datetime(2026, 8, 11, 13, 0, tzinfo=UTC),
        has_releases=True,
    )

    assert decision.due is True
    assert decision.send_at == datetime(2026, 8, 11, 14, 30, tzinfo=UTC)


def test_digest_hard_cutoff_caps_continuous_releases() -> None:
    schedule = DailyDigestSchedule()

    decision = schedule.decide(
        now=datetime(2026, 8, 11, 15, 30, tzinfo=UTC),
        timezone=SHANGHAI,
        latest_release_at=datetime(2026, 8, 11, 15, 25, tzinfo=UTC),
        has_releases=True,
    )

    assert decision.due is True
    assert decision.send_at == datetime(2026, 8, 11, 15, 30, tzinfo=UTC)


def test_digest_after_cutoff_targets_next_period_and_never_sends_empty() -> None:
    schedule = DailyDigestSchedule()

    decision = schedule.decide(
        now=datetime(2026, 8, 11, 15, 45, tzinfo=UTC),
        timezone=SHANGHAI,
        latest_release_at=None,
        has_releases=False,
    )

    assert decision.period_date == date(2026, 8, 12)
    assert decision.due is False
    assert decision.send_at is None
    assert decision.period_start == datetime(2026, 8, 11, 15, 30, tzinfo=UTC)
    assert decision.period_end == datetime(2026, 8, 12, 15, 30, tzinfo=UTC)
