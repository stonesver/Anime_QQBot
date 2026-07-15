from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from anime_qqbot.catalog.models import AiringOccurrence, AnimeWeek, Season, SeasonName


def test_season_boundaries() -> None:
    winter = Season(2026, SeasonName.WINTER)
    spring = Season(2026, SeasonName.SPRING)
    summer = Season(2026, SeasonName.SUMMER)
    autumn = Season(2026, SeasonName.AUTUMN)

    assert winter.date_range == (date(2026, 1, 1), date(2026, 3, 31))
    assert spring.date_range == (date(2026, 4, 1), date(2026, 6, 30))
    assert summer.date_range == (date(2026, 7, 1), date(2026, 9, 30))
    assert autumn.date_range == (date(2026, 10, 1), date(2026, 12, 31))
    assert Season.from_date(date(2026, 12, 31)) == autumn


def test_occurrence_converts_to_group_timezone() -> None:
    occurrence = AiringOccurrence(
        subject_id=1,
        air_date=date(2026, 7, 15),
        air_at=datetime(2026, 7, 15, 16, 30, tzinfo=UTC),
        episode=2,
        source="bangumi-data",
    )

    assert occurrence.in_timezone(ZoneInfo("Asia/Shanghai")) == datetime(
        2026, 7, 16, 0, 30, tzinfo=ZoneInfo("Asia/Shanghai")
    )


def test_week_range_uses_local_calendar_across_year() -> None:
    starts_on, ends_on = AnimeWeek.range_containing(date(2027, 1, 1))

    assert starts_on == date(2026, 12, 28)
    assert ends_on == date(2027, 1, 3)
