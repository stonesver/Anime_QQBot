"""Unit tests for release batching (Task 25)."""

from __future__ import annotations

from datetime import UTC, datetime

from anime_qqbot.resources.batching import BatchManager


def test_window_is_not_ready_before_10_minutes() -> None:
    mgr = BatchManager(window_minutes=10)
    opened = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    now = datetime(2026, 6, 1, 12, 5, tzinfo=UTC)

    assert mgr.is_ready(opened, now) is False
    assert mgr.should_open_batch(opened, now) is True


def test_window_is_ready_after_10_minutes() -> None:
    mgr = BatchManager(window_minutes=10)
    opened = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    now = datetime(2026, 6, 1, 12, 10, tzinfo=UTC)

    assert mgr.is_ready(opened, now) is True
    assert mgr.should_open_batch(opened, now) is False


def test_filter_returns_at_most_5() -> None:
    mgr = BatchManager()
    releases = list(range(10))  # 10 dummy objects

    result = mgr.filter_for_user(releases)
    assert len(result) == 5
