from __future__ import annotations

from anime_tracking_plugin.adapter import Reply
from anime_tracking_plugin.tool_image_presenter import ToolImagePresenter


class Event:
    def __init__(self) -> None:
        self.sent = []
        self.extras = {}
        self.stopped = False

    async def send(self, chain) -> None:
        self.sent.append(chain)

    def set_extra(self, key: str, value: object) -> None:
        self.extras[key] = value

    def stop_event(self) -> None:
        self.stopped = True


async def test_safe_local_image_is_sent_once_and_stops_current_agent(tmp_path) -> None:
    image = tmp_path / "today.png"
    image.touch()
    event = Event()

    sent = await ToolImagePresenter(
        asset_root=tmp_path,
        stop_settle_seconds=0,
    ).send(event, Reply.from_image(image, fallback_text="今日放送"))

    assert sent is True
    assert len(event.sent) == 1
    assert event.sent[0].chain == [{"type": "image", "file": str(image)}]
    assert event.extras["agent_stop_requested"] is True
    assert event.stopped is True
