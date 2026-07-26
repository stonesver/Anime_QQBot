"""Unit tests for the fixed-command intent parser (Task 6)."""

from __future__ import annotations

import pytest

from anime_qqbot.application import (
    Intent,
    IntentKind,
    ParseFailure,
    is_internal_id,
    parse_fixed_command,
)

_INTERNAL_ID = "12345678-1234-1234-1234-123456789012"


def test_internal_id_helper() -> None:
    assert is_internal_id(_INTERNAL_ID)
    assert not is_internal_id("not-a-uuid")
    assert not is_internal_id("42")


@pytest.mark.parametrize(
    ("content", "kind"),
    [
        ("/番剧 本周", IntentKind.WEEK),
        ("/番剧 我的订阅", IntentKind.MY_SUBSCRIPTIONS),
        ("/番剧 状态", IntentKind.STATUS),
        ("/番剧 映射待处理", IntentKind.MAPPING_PENDING),
        ("/番剧 帮助", IntentKind.HELP),
    ],
)
def test_simple_subcommands(content: str, kind: IntentKind) -> None:
    intent = parse_fixed_command(content)

    assert isinstance(intent, Intent)
    assert intent.kind == kind


def test_today_with_explicit_date() -> None:
    intent = parse_fixed_command("/番剧 今天 2026-07-15")

    assert isinstance(intent, Intent)
    assert intent.kind == IntentKind.TODAY
    assert intent.query == "2026-07-15"


def test_today_without_date_uses_today() -> None:
    intent = parse_fixed_command("/番剧 今天")

    assert isinstance(intent, Intent)
    assert intent.kind == IntentKind.TODAY
    assert intent.query is None or intent.query == ""


def test_today_invalid_date_returns_failure() -> None:
    result = parse_fixed_command("/番剧 今天 2026-13-40")

    assert isinstance(result, ParseFailure)


def test_season_with_year_and_name() -> None:
    intent = parse_fixed_command("/番剧 季度 2026 夏")

    assert isinstance(intent, Intent)
    assert intent.kind == IntentKind.SEASON
    assert intent.season_year == 2026
    assert intent.season_name == "summer"


def test_season_with_name_only_uses_current_year() -> None:
    intent = parse_fixed_command("/番剧 季度 夏")

    assert isinstance(intent, Intent)
    assert intent.kind == IntentKind.SEASON
    assert intent.season_year is not None
    assert intent.season_name == "summer"


def test_season_invalid_name() -> None:
    result = parse_fixed_command("/番剧 季度 2026 五")

    assert isinstance(result, ParseFailure)


def test_search_requires_keyword() -> None:
    intent = parse_fixed_command("/番剧 搜索 夏日")

    assert isinstance(intent, Intent)
    assert intent.kind == IntentKind.SEARCH
    assert intent.query == "夏日"


def test_search_without_keyword_fails() -> None:
    result = parse_fixed_command("/番剧 搜索")

    assert isinstance(result, ParseFailure)


def test_detail_with_internal_id_sets_anime_id() -> None:
    intent = parse_fixed_command(f"/番剧 详情 {_INTERNAL_ID}")

    assert isinstance(intent, Intent)
    assert intent.kind == IntentKind.DETAIL
    assert intent.anime_id == _INTERNAL_ID
    assert intent.query is None


def test_detail_with_keyword_uses_query() -> None:
    intent = parse_fixed_command("/番剧 详情 夏日物语")

    assert isinstance(intent, Intent)
    assert intent.kind == IntentKind.DETAIL
    assert intent.query == "夏日物语"
    assert intent.anime_id is None


def test_subscribe_requires_confirmation() -> None:
    intent = parse_fixed_command(f"/番剧 订阅 {_INTERNAL_ID}")

    assert isinstance(intent, Intent)
    assert intent.kind == IntentKind.SUBSCRIBE
    assert intent.requires_confirmation is True


def test_unsubscribe_requires_confirmation() -> None:
    intent = parse_fixed_command(f"/番剧 取消订阅 {_INTERNAL_ID}")

    assert isinstance(intent, Intent)
    assert intent.kind == IntentKind.UNSUBSCRIBE
    assert intent.requires_confirmation is True


def test_subscription_settings_parses_filters() -> None:
    intent = parse_fixed_command(f"/番剧 订阅设置 {_INTERNAL_ID} 语言=简体 字幕组=A,B 分辨率=1080p")

    assert isinstance(intent, Intent)
    assert intent.kind == IntentKind.SUBSCRIPTION_SETTINGS
    assert intent.language == "简体"
    assert intent.subtitle_groups == ("A", "B")


def test_subscription_settings_requires_internal_id() -> None:
    result = parse_fixed_command("/番剧 订阅设置 夏日物语")

    assert isinstance(result, ParseFailure)


def test_unknown_subcommand_returns_failure() -> None:
    result = parse_fixed_command("/番剧 未知子命令")

    assert isinstance(result, ParseFailure)


def test_missing_prefix_returns_failure() -> None:
    result = parse_fixed_command("今天")

    assert isinstance(result, ParseFailure)


def test_intent_state_change_immutable_post_init() -> None:
    intent = Intent(
        kind=IntentKind.SUBSCRIBE,
        anime_id=_INTERNAL_ID,
        requires_confirmation=False,
    )

    assert intent.requires_confirmation is True


def test_intent_query_state_has_no_confirmation() -> None:
    intent = Intent(
        kind=IntentKind.SEARCH,
        query="夏日",
    )

    assert intent.requires_confirmation is False
