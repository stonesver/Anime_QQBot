from __future__ import annotations

from datetime import timedelta

from anime_qqbot.notifications.governor import (
    DeliveryClass,
    GovernorLimits,
    SendGovernor,
    SendRequest,
)


def test_same_group_and_user_are_cooled_down(frozen_clock) -> None:
    governor = SendGovernor(clock=frozen_clock)
    request = SendRequest(DeliveryClass.INTERACTIVE, "g1", "u1")

    assert governor.acquire(request).allowed
    denied = governor.acquire(request)
    assert denied.allowed is False
    assert denied.reason in {"group", "user"}
    assert denied.retry_after_seconds == 5


def test_other_group_can_use_global_burst(frozen_clock) -> None:
    governor = SendGovernor(clock=frozen_clock)

    assert governor.acquire(SendRequest(DeliveryClass.INTERACTIVE, "g1", "u1")).allowed
    assert governor.acquire(SendRequest(DeliveryClass.INTERACTIVE, "g2", "u2")).allowed
    assert not governor.acquire(SendRequest(DeliveryClass.INTERACTIVE, "g3", "u3")).allowed


def test_proactive_messages_have_stricter_group_window(frozen_clock) -> None:
    limits = GovernorLimits(
        global_interval_seconds=0.1,
        global_burst=10,
        group_interval_seconds=0.1,
        proactive_group_interval_seconds=60,
    )
    governor = SendGovernor(clock=frozen_clock, limits=limits)
    request = SendRequest(DeliveryClass.AIRING, "g1")

    assert governor.acquire(request).allowed
    frozen_clock.advance(timedelta(seconds=1))
    denied = governor.acquire(request)
    assert denied.reason == "proactive_group"
    assert denied.retry_after_seconds == 59


def test_peek_does_not_consume_capacity(frozen_clock) -> None:
    governor = SendGovernor(clock=frozen_clock)
    request = SendRequest(DeliveryClass.ADMIN, "g1", "owner")

    assert governor.peek(request).allowed
    assert governor.peek(request).allowed
    assert governor.acquire(request).allowed
