"""Unit tests for release batching (Task 25)."""

from __future__ import annotations

from datetime import UTC, datetime

from anime_qqbot.resources.batching import BatchManager
from anime_qqbot.resources.parser import ParsedRelease


def test_window_is_not_ready_before_10_minutes() -> None:
    mgr = BatchManager(window_minutes=10)
    opened = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    now = datetime(2026, 6, 1, 12, 5, tzinfo=UTC)

    assert mgr.is_ready(opened, now) is False
    assert mgr.should_open_batch(opened, now) is True


def test_window_is_ready_after_10_minutes() -> None:
    mgr = BatchManager(window_minutes=10)
    opened = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    now = datetime(2026, 6, 1, 12, 10, tzinfo=UTC)

    assert mgr.is_ready(opened, now) is True
    assert mgr.should_open_batch(opened, now) is False


def _release(
    *,
    language: str | None,
    groups: tuple[str, ...] = ("Group A",),
    resolutions: tuple[str, ...] = ("1080p",),
) -> ParsedRelease:
    return ParsedRelease(
        episode_label="01",
        subtitle_groups=groups,
        language=language,
        resolutions=resolutions,
        spec_tags=(),
        parser_version="v1",
        parse_warnings=(),
    )


def test_filter_matches_explicit_language_group_and_resolution() -> None:
    mgr = BatchManager()
    matching = _release(language="chs")
    wrong_language = _release(language="cht")
    wrong_group = _release(language="chs", groups=("Group B",))
    wrong_resolution = _release(language="chs", resolutions=("720p",))

    result = mgr.filter_for_user(
        [matching, wrong_language, wrong_group, wrong_resolution],
        language="chs",
        subtitle_groups=("group a",),
        resolutions=("1080P",),
    )

    assert result == [matching]


def test_unknown_values_only_match_unrestricted_filters() -> None:
    mgr = BatchManager()
    unknown = _release(language=None, groups=(), resolutions=())

    assert mgr.filter_for_user([unknown]) == [unknown]
    assert mgr.filter_for_user([unknown], language="chs") == []
    assert mgr.filter_for_user([unknown], subtitle_groups=("Group A",)) == []
    assert mgr.filter_for_user([unknown], resolutions=("1080p",)) == []


def test_filter_does_not_truncate_matches() -> None:
    mgr = BatchManager()
    releases = [_release(language="chs") for _ in range(7)]

    result = mgr.filter_for_user(releases)
    assert len(result) == 7
