from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from astrbot_plugin_anime_tracking.anime_tracking_plugin.adapter import Reply
from astrbot_plugin_anime_tracking.anime_tracking_plugin.rendering import (
    render_airing_notification,
    render_release_batch,
    render_reply,
    reply_to_event_result,
)


class Event:
    def plain_result(self, text: str):
        return {"kind": "plain", "text": text}

    def chain_result(self, chain):
        return {"kind": "chain", "chain": chain}


def test_plain_reply_remains_plain_text(tmp_path: Path) -> None:
    rendered = render_reply(Reply.from_text("hello"), asset_root=tmp_path)

    assert rendered.text == "hello"
    assert rendered.chain is None
    assert reply_to_event_result(Event(), Reply.from_text("hello"), asset_root=tmp_path) == {
        "kind": "plain",
        "text": "hello",
    }


def test_local_cached_png_becomes_image_then_plain_chain(tmp_path: Path) -> None:
    card = tmp_path / "renders" / "card.png"
    card.parent.mkdir()
    card.touch()

    rendered = render_reply(
        Reply.from_image(card, hint="追番提示"),
        asset_root=tmp_path,
    )

    assert rendered.chain == [
        {"type": "image", "file": str(card)},
        {"type": "plain", "text": "追番提示"},
    ]


@pytest.mark.parametrize(
    ("renderer", "payload"),
    [
        (
            render_airing_notification,
            {
                "display_title": "测试番剧",
                "episode_label": "01",
                "at_user_ids": ["1486315284"],
            },
        ),
        (
            render_release_batch,
            {
                "text": "[资源发布] 测试番剧 第01集",
                "at_user_ids": ["1486315284"],
            },
        ),
    ],
)
def test_notification_renderer_returns_message_chain(renderer, payload) -> None:
    rendered = renderer(payload)

    assert hasattr(rendered, "chain")
    assert [item["type"] for item in rendered.chain] == ["at", "plain"]


def test_structured_release_notification_is_compact_and_uses_shanghai_time() -> None:
    rendered = render_release_batch(
        {
            "display_title": "BanG Dream! YUME∞MITA",
            "episode_label": "06",
            "at_user_ids": ["1486315284"],
            "release_count": 4,
            "releases": [
                {
                    "subtitle_group": "ANi",
                    "language": "cht",
                    "resolution": "1080p",
                    "pub_date": "2026-07-23T22:00:46.579020+00:00",
                },
                {
                    "subtitle_group": "Prejudice-Studio",
                    "language": "chs",
                    "resolution": "1080p",
                    "pub_date": "2026-07-23T23:36:33.907626+00:00",
                },
                {
                    "subtitle_group": "LoliHouse",
                    "language": None,
                    "resolution": "1080p",
                    "pub_date": "2026-07-24T00:12:00+00:00",
                },
            ],
            "detail_query": "BanG Dream! YUME∞MITA",
        }
    )

    text = rendered.chain[-1]["text"]
    assert text == (
        " 📦 BanG Dream! YUME∞MITA · 第 6 集\n"
        "发现 4 个资源\n"
        "• ANi · 繁中 · 1080p · 07-24 06:00\n"
        "• Prejudice-Studio · 简中 · 1080p · 07-24 07:36\n"
        "• LoliHouse · 语言未知 · 1080p · 07-24 08:12\n"
        "另有 1 个资源\n\n"
        "发送「资源详情 BanG Dream! YUME∞MITA 6」查看来源"
    )
    assert "https://" not in text
    assert "2026-07-23T" not in text


def test_release_notification_keeps_legacy_text_payload_compatible() -> None:
    rendered = render_release_batch(
        {
            "text": "[资源发布] 旧任务正文",
            "at_user_ids": ["1486315284"],
        }
    )

    assert rendered.chain[-1]["text"] == "[资源发布] 旧任务正文"


@pytest.mark.parametrize(
    ("enabled", "sources", "url", "expected"),
    [
        (
            False,
            ("bilibili",),
            "https://www.bilibili.com/video/BV1xx411c7mD",
            False,
        ),
        (
            True,
            ("bilibili",),
            "https://www.bilibili.com/video/BV1xx411c7mD",
            True,
        ),
        (True, ("bilibili",), "https://b23.tv/example", False),
        (True, ("bilibili",), "https://example.com/video/BV1xx411c7mD", False),
    ],
)
def test_release_action_link_is_explicit_and_allowlisted(
    enabled: bool,
    sources: tuple[str, ...],
    url: str,
    expected: bool,
) -> None:
    rendered = render_release_batch(
        {
            "display_title": "测试番剧",
            "episode_label": "1",
            "release_count": 1,
            "releases": [],
            "action_label": "UP 主更新",
            "action_source": "bilibili",
            "action_url": url,
        },
        proactive_action_links_enabled=enabled,
        proactive_action_link_sources=sources,
    )

    text = rendered.chain[-1]["text"]
    assert (url in text) is expected
    assert ("🎬 相关视频：UP 主更新" in text) is expected


def test_release_action_label_cannot_smuggle_another_url() -> None:
    rendered = render_release_batch(
        {
            "display_title": "测试番剧",
            "episode_label": "1",
            "release_count": 0,
            "releases": [],
            "action_label": "https://example.com",
            "action_source": "bilibili",
            "action_url": "https://www.bilibili.com/video/BV1xx411c7mD",
        },
        proactive_action_links_enabled=True,
        proactive_action_link_sources=("bilibili",),
    )

    assert "https://" not in rendered.chain[-1]["text"]


@pytest.mark.parametrize(
    "path",
    [
        Path("/tmp/not-in-cache.png"),
        Path("https:/example.com/card.png"),
    ],
)
def test_rejects_non_local_or_out_of_root_images(tmp_path: Path, path: Path) -> None:
    with pytest.raises(ValueError):
        render_reply(Reply.from_image(path), asset_root=tmp_path)
