"""Worker source-sync scheduling tests."""

from datetime import UTC, datetime, timedelta

from anime_qqbot.entrypoints.cli import _catalog_sync_is_due


def test_catalog_sync_runs_initially_then_only_when_due() -> None:
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    next_sync_at = now + timedelta(hours=6)

    assert _catalog_sync_is_due(now, None)
    assert not _catalog_sync_is_due(now, next_sync_at)
    assert _catalog_sync_is_due(next_sync_at, next_sync_at)
