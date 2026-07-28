"""Application layer: platform-neutral chat context, intent types, use cases."""

from anime_qqbot.application.context import ChatContext
from anime_qqbot.application.intents import Intent, IntentKind
from anime_qqbot.application.module import (
    ParseFailure,
    is_internal_id,
    parse_fixed_command,
)
from anime_qqbot.application.use_cases import (
    QueryResult,
    SubscribeResult,
    claim_pending_job,
    claim_pending_jobs,
    complete_job,
    detail_for,
    my_subscriptions,
    next_airing_for,
    pending_mappings,
    release_expired_leases,
    search_anime,
    season_listing,
    source_freshness,
    subscribe,
    subscription_settings,
    today_listing,
    unsubscribe,
    week_listing,
)

__all__ = [
    "ChatContext",
    "Intent",
    "IntentKind",
    "ParseFailure",
    "QueryResult",
    "SubscribeResult",
    "claim_pending_job",
    "claim_pending_jobs",
    "complete_job",
    "detail_for",
    "is_internal_id",
    "my_subscriptions",
    "next_airing_for",
    "parse_fixed_command",
    "pending_mappings",
    "release_expired_leases",
    "search_anime",
    "season_listing",
    "source_freshness",
    "subscribe",
    "subscription_settings",
    "today_listing",
    "unsubscribe",
    "week_listing",
]
