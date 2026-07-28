from __future__ import annotations

import pytest

from anime_qqbot.application.intents import Intent, IntentKind
from anime_qqbot.application.parser import ParseFailure
from anime_qqbot.interactions.parser import parse_direct_shortcut


@pytest.mark.parametrize(
    ("content", "kind"),
    [
        ("今日番剧", IntentKind.TODAY),
        ("本周番剧", IntentKind.WEEK),
        ("我的追番", IntentKind.MY_SUBSCRIPTIONS),
        ("搜番 葬送的芙莉莲", IntentKind.SEARCH),
        ("追番 2", IntentKind.SUBSCRIBE),
        ("退订 2", IntentKind.UNSUBSCRIBE),
    ],
)
def test_direct_shortcuts_are_explicit(content: str, kind: IntentKind) -> None:
    result = parse_direct_shortcut(content)

    assert isinstance(result, Intent)
    assert result.kind == kind


@pytest.mark.parametrize(
    "content",
    [
        "今天看的番剧真不错",
        "本周我们一起搜索一下",
        "我想订阅这个频道",
        "能不能推荐番剧",
        "搜番",
        "今日番剧怎么样",
        "他发了今日番剧",
    ],
)
def test_ordinary_conversation_never_matches(content: str) -> None:
    assert isinstance(parse_direct_shortcut(content), ParseFailure)


def test_number_is_candidate_selection_not_free_text() -> None:
    result = parse_direct_shortcut("追番 3")

    assert isinstance(result, Intent)
    assert result.selection_number == 3
    assert result.query is None
