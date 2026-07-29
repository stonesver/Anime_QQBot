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
