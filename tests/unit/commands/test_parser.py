import pytest

from anime_qqbot.commands.models import CommandKind
from anime_qqbot.commands.parser import CommandParser


@pytest.mark.parametrize(
    ("content", "kind", "arguments"),
    [
        (" 今日番剧 ", CommandKind.TODAY, ()),
        ("今日番剧 2026-07-15", CommandKind.TODAY, ("2026-07-15",)),
        ("周番表", CommandKind.WEEK, ()),
        ("季度番剧 2026 夏", CommandKind.SEASON, ("2026", "夏")),
        ("搜索  夏日  物语 ", CommandKind.SEARCH, ("夏日", "物语")),
        ("番剧 1001", CommandKind.DETAIL, ("1001",)),
        ("下次更新 1001", CommandKind.NEXT_AIRING, ("1001",)),
        ("订阅 1001", CommandKind.SUBSCRIBE, ("1001",)),
        ("取消订阅 1001", CommandKind.UNSUBSCRIBE, ("1001",)),
        ("开启每日推送 08:30", CommandKind.ENABLE_DAILY, ("08:30",)),
        ("开启每周推送 一 09:00", CommandKind.ENABLE_WEEKLY, ("一", "09:00")),
    ],
)
def test_parses_supported_commands(
    content: str, kind: CommandKind, arguments: tuple[str, ...]
) -> None:
    intent = CommandParser().parse(content)
    assert intent.kind is kind
    assert intent.arguments == arguments
    assert intent.valid


@pytest.mark.parametrize(
    "content", ["今日番剧 2026-13-01", "季度番剧 2026 雨", "开启每日推送 25:00"]
)
def test_reports_invalid_arguments(content: str) -> None:
    intent = CommandParser().parse(content)
    assert not intent.valid and intent.error


def test_unknown_command_becomes_deterministic_help() -> None:
    intent = CommandParser().parse("帮我看看有什么番")
    assert intent.kind is CommandKind.HELP
    assert intent.error == "未识别命令"
