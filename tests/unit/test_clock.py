from datetime import UTC, datetime, timedelta

from anime_qqbot.clock import FrozenClock, SystemClock


def test_system_clock_returns_aware_utc_time() -> None:
    now = SystemClock().now()

    assert now.tzinfo is UTC


def test_frozen_clock_can_advance_deterministically() -> None:
    clock = FrozenClock(datetime(2026, 7, 15, 8, 0, tzinfo=UTC))

    clock.advance(timedelta(minutes=30))

    assert clock.now() == datetime(2026, 7, 15, 8, 30, tzinfo=UTC)
