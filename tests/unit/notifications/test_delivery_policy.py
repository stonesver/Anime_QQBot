from datetime import UTC, datetime, timedelta

from anime_qqbot.notifications.delivery import decide_delivery
from anime_qqbot.qq.contracts import DeliveryOutcome, DeliveryResult


def test_unknown_is_never_automatically_retried() -> None:
    decision = decide_delivery(
        DeliveryResult(DeliveryOutcome.UNKNOWN), 1, datetime(2026, 7, 15, tzinfo=UTC)
    )
    assert decision.job_status == "unknown"
    assert decision.retry_at is None


def test_rate_limit_honours_retry_after() -> None:
    now = datetime(2026, 7, 15, tzinfo=UTC)
    decision = decide_delivery(
        DeliveryResult(DeliveryOutcome.RATE_LIMITED, retry_after_seconds=30), 1, now
    )
    assert decision.job_status == "pending"
    assert decision.retry_at == now + timedelta(seconds=30)


def test_retry_limit_becomes_failed() -> None:
    decision = decide_delivery(
        DeliveryResult(DeliveryOutcome.RATE_LIMITED), 3, datetime(2026, 7, 15, tzinfo=UTC)
    )
    assert decision.job_status == "failed"
