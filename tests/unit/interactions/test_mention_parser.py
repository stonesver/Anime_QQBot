import pytest

from anime_qqbot.application.intents import Intent, IntentKind
from anime_qqbot.application.parser import ParseFailure
from anime_qqbot.interactions.mention_policy import (
    DEFAULT_MENTION_ALIASES,
    MentionCommandPolicy,
    MentionPolicyValidationError,
)
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


def test_global_alias_policy_replaces_one_actions_trigger_words() -> None:
    aliases = {key: list(values) for key, values in DEFAULT_MENTION_ALIASES.items()}
    aliases["today"] = ["今天更新啥"]
    policy = MentionCommandPolicy.from_mapping(aliases)

    custom = parse_mention_command("今天更新啥", policy=policy)

    assert isinstance(custom, Intent)
    assert custom.kind == IntentKind.TODAY
    assert isinstance(parse_mention_command("今天有什么番", policy=policy), ParseFailure)


def test_global_alias_policy_rejects_non_list_values_and_conflicts() -> None:
    aliases: dict[str, object] = {
        key: list(values) for key, values in DEFAULT_MENTION_ALIASES.items()
    }
    aliases["today"] = {"unexpected": "object"}
    with pytest.raises(MentionPolicyValidationError, match="today aliases must be a list"):
        MentionCommandPolicy.from_mapping(aliases)  # type: ignore[arg-type]

    aliases = {key: list(values) for key, values in DEFAULT_MENTION_ALIASES.items()}
    aliases["week"] = [str(aliases["today"][0])]  # type: ignore[index]
    with pytest.raises(MentionPolicyValidationError, match="conflicts"):
        MentionCommandPolicy.from_mapping(aliases)  # type: ignore[arg-type]
