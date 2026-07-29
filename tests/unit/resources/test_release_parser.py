"""Unit tests for Mikan release title parser (Task 23)."""

from __future__ import annotations

from anime_qqbot.resources.parser import (
    PARSER_VERSION,
    ParsedRelease,
    parse_release_title,
)


def test_parses_standard_chinese_episode() -> None:
    result = parse_release_title("[桜都字幕组] 夏日物语 / Natsu Monogatari [07] [1080p][简日双语]")

    assert result.episode_label == "07"
    assert "桜都字幕组" in result.subtitle_groups
    assert result.language == "chs"
    assert "1080p" in result.resolutions
    assert result.parser_version == PARSER_VERSION


def test_parses_dash_episode_without_confusing_resolution() -> None:
    result = parse_release_title(
        "[ANi] 感谢对战。～大小姐才不玩格斗游戏～ - 01 [1080P][Baha][WEB-DL][AAC AVC][CHT][MP4]"
    )

    assert result.episode_label == "01"
    assert result.resolutions == ("1080p",)


def test_resolution_block_is_not_an_episode() -> None:
    result = parse_release_title("[ANi] Example Anime [1080P][CHT]")

    assert result.episode_label is None
    assert "unknown_episode" in result.parse_warnings


def test_unknown_episode_warns() -> None:
    result = parse_release_title("[SomeGroup] Music Collection [FLAC]")

    assert result.episode_label is None
    assert "unknown_episode" in result.parse_warnings


def test_too_long_title_is_rejected() -> None:
    long_title = "A" * 2048
    result = parse_release_title(long_title)

    assert result.episode_label is None
    assert "title_too_long" in result.parse_warnings


def test_ova_detected_as_special() -> None:
    result = parse_release_title("[SubGroup] 劇場版 Summer [OVA][1080p]")

    assert "OVA" in result.spec_tags


def test_no_regex_catastrophic_backtracking() -> None:
    # Long repetitive input should not hang or throw.
    title = "[AAAA]" * 200 + "Episode [01]"
    result = parse_release_title(title)

    assert result is not None
    assert isinstance(result, ParsedRelease)
