from anime_qqbot.application.intents import Intent, IntentKind
from anime_qqbot.application.parser import ParseFailure
from anime_qqbot.interactions.parser import parse_mention_command, parse_reply_number


def test_mention_supports_limited_synonym() -> None:
    result = parse_mention_command("找番 胆大党")

    assert isinstance(result, Intent)
    assert result.kind == IntentKind.SEARCH
    assert result.query == "胆大党"


def test_mention_number_selects_detail() -> None:
    result = parse_mention_command("看 2")

    assert isinstance(result, Intent)
    assert result.kind == IntentKind.DETAIL
    assert result.selection_number == 2


def test_mention_does_not_guess_natural_language() -> None:
    assert isinstance(parse_mention_command("你觉得今天有什么好看的"), ParseFailure)


def test_plain_number_has_separate_reply_parser() -> None:
    result = parse_reply_number("2")

    assert isinstance(result, Intent)
    assert result.selection_number == 2
    assert isinstance(parse_reply_number("第 2 个"), ParseFailure)
