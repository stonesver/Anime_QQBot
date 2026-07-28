from anime_qqbot.notifications.outcomes import DeliveryOutcome, DeliveryOutcomeKind


def test_unknown_is_not_retried_automatically() -> None:
    outcome = DeliveryOutcome(DeliveryOutcomeKind.UNKNOWN, "unexpected")

    assert outcome.retryable is False
    assert outcome.opens_global_circuit is False


def test_account_offline_opens_global_circuit() -> None:
    outcome = DeliveryOutcome(DeliveryOutcomeKind.ACCOUNT_OFFLINE, "offline")

    assert outcome.retryable is False
    assert outcome.opens_global_circuit is True
