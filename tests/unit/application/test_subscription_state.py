from datetime import UTC, datetime

from anime_qqbot.application.subscription_state import (
    SubscriptionOccurrence,
    SubscriptionStateKind,
    classify_subscription,
)


def test_reaches_known_total_is_completed() -> None:
    state = classify_subscription(
        next_occurrence=None,
        latest_episode=12,
        total_episodes=12,
        source_statuses=(),
    )

    assert state.kind is SubscriptionStateKind.COMPLETED


def test_finished_source_status_is_completed_without_schedule() -> None:
    state = classify_subscription(
        next_occurrence=None,
        latest_episode=None,
        total_episodes=None,
        source_statuses=("FINISHED",),
    )

    assert state.kind is SubscriptionStateKind.COMPLETED


def test_future_occurrence_is_the_active_next_episode() -> None:
    occurrence = SubscriptionOccurrence(
        episode_label="05",
        air_at=datetime(2026, 8, 5, 14, 0, tzinfo=UTC),
    )

    state = classify_subscription(
        next_occurrence=occurrence,
        latest_episode=4,
        total_episodes=12,
        source_statuses=("RELEASING",),
    )

    assert state.kind is SubscriptionStateKind.ACTIVE
    assert state.next_occurrence == occurrence


def test_missing_next_schedule_waits_without_marking_completed() -> None:
    state = classify_subscription(
        next_occurrence=None,
        latest_episode=4,
        total_episodes=12,
        source_statuses=(),
    )

    assert state.kind is SubscriptionStateKind.WAITING
