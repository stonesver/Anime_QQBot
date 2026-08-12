from datetime import UTC, date, datetime, timedelta

from anime_qqbot.catalog.airing_resolver import SourcedAiring, resolve_airing
from anime_qqbot.catalog.models import AiringOccurrence


def occurrence(source: str, *, hour: int | None) -> SourcedAiring:
    air_at = datetime(2026, 8, 12, hour, tzinfo=UTC) if hour is not None else None
    return SourcedAiring(
        provider=source,
        occurrence=AiringOccurrence(
            subject_id=1,
            air_date=date(2026, 8, 12),
            air_at=air_at,
            episode=6,
            source=source,
        ),
    )


def test_prefers_animeschedule_then_anilist_then_bangumi() -> None:
    resolved = resolve_airing(
        [
            occurrence("bangumi", hour=None),
            occurrence("anilist", hour=14),
            occurrence("animeschedule", hour=15),
        ]
    )

    assert resolved.selected is not None
    assert resolved.selected.provider == "animeschedule"
    assert resolved.conflict is False
    assert resolved.proactive_allowed is True


def test_exact_sources_over_six_hours_apart_suppress_proactive_notification() -> None:
    resolved = resolve_airing(
        [occurrence("anilist", hour=8), occurrence("animeschedule", hour=15)],
        conflict_threshold=timedelta(hours=6),
    )

    assert resolved.selected is not None
    assert resolved.selected.provider == "animeschedule"
    assert resolved.conflict is True
    assert resolved.proactive_allowed is False
    assert {item.provider for item in resolved.conflicting} == {"anilist", "animeschedule"}
