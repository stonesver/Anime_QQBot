"""Translate platform exceptions into stable delivery outcomes."""

from __future__ import annotations

from anime_qqbot.notifications.outcomes import DeliveryOutcome, DeliveryOutcomeKind


def classify_delivery_exception(exc: Exception) -> DeliveryOutcome:
    text = str(exc).casefold()
    if any(token in text for token in ("账号下线", "account offline", "not logged in", "登录失效")):
        return DeliveryOutcome(DeliveryOutcomeKind.ACCOUNT_OFFLINE, "account offline")
    if any(token in text for token in ("rate limit", "too many", "频率", "风控")):
        return DeliveryOutcome(DeliveryOutcomeKind.RATE_LIMITED, "platform rate limited")
    if any(token in text for token in ("timeout", "timed out", "connection", "temporar", "down")):
        return DeliveryOutcome(DeliveryOutcomeKind.TEMPORARY, "temporary transport failure")
    if any(token in text for token in ("forbidden", "permission", "not in group", "被禁言")):
        return DeliveryOutcome(DeliveryOutcomeKind.PERMANENT, "delivery not permitted")
    return DeliveryOutcome(DeliveryOutcomeKind.UNKNOWN, "unclassified delivery failure")


__all__ = ["classify_delivery_exception"]
