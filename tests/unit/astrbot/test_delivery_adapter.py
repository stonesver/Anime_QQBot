from anime_tracking_plugin.delivery_adapter import classify_delivery_exception

from anime_qqbot.notifications.outcomes import DeliveryOutcomeKind


def test_rate_control_exception_is_rate_limited() -> None:
    outcome = classify_delivery_exception(RuntimeError("账号触发风控，请稍后"))

    assert outcome.kind == DeliveryOutcomeKind.RATE_LIMITED
    assert outcome.retryable is True


def test_unknown_exception_is_not_retried() -> None:
    outcome = classify_delivery_exception(RuntimeError("strange code 771"))

    assert outcome.kind == DeliveryOutcomeKind.UNKNOWN
    assert outcome.retryable is False
