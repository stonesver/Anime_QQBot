"""Map platform-neutral replies to AstrBot message components."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anime_qqbot.resources.presentation import format_release_notification

from .adapter import Reply

try:
    import astrbot.api.message_components as components  # type: ignore[import-not-found]
    from astrbot.api.event import (
        MessageChain as AstrBotMessageChain,  # type: ignore[import-not-found]
    )
except ModuleNotFoundError:
    AstrBotMessageChain = None  # type: ignore[assignment,misc]
    components = None  # type: ignore[assignment]


@dataclass(frozen=True)
class RenderedReply:
    text: str | None = None
    chain: list[Any] | None = None


@dataclass
class OfflineMessageChain:
    chain: list[Any]


def render_reply(reply: Reply, *, asset_root: Path) -> RenderedReply:
    parts: list[str] = []
    chain: list[Any] = []
    for block in reply.blocks:
        if block.image_path is not None:
            path = block.image_path.resolve()
            if (
                not path.is_relative_to(asset_root.resolve())
                or not path.is_file()
                or path.suffix.lower() != ".png"
            ):
                raise ValueError("reply image must be a local cached PNG")
            chain.append(_image_component(path))
        if block.text:
            parts.append(block.text)
            if chain:
                chain.append(_plain_component(block.text))

    if reply.candidates:
        parts.append("多个结果，请通过编号选择：")
        for index, candidate in enumerate(reply.candidates, start=1):
            parts.append(f"  {index}. {candidate}")
    if reply.error:
        parts.append(f"错误: {reply.error}")

    text = "\n".join(parts) if parts else "（无内容）"
    if chain:
        return RenderedReply(chain=chain)
    return RenderedReply(text=text)


def reply_to_event_result(event: Any, reply: Reply, *, asset_root: Path) -> Any:
    rendered = render_reply(reply, asset_root=asset_root)
    if rendered.chain is not None:
        return event.chain_result(rendered.chain)
    return event.plain_result(rendered.text or "（无内容）")


def _image_component(path: Path) -> Any:
    if components is None:
        return {"type": "image", "file": str(path)}
    return components.Image.fromFileSystem(str(path))


def _plain_component(text: str) -> Any:
    if components is None:
        return {"type": "plain", "text": text}
    return components.Plain(text)


def _at_component(user_id: object) -> Any:
    if components is None:
        return {"type": "at", "qq": str(user_id)}
    return components.At(qq=str(user_id))


def _message_chain(chain: list[Any]) -> Any:
    if AstrBotMessageChain is None:
        return OfflineMessageChain(chain)
    return AstrBotMessageChain(chain=chain)


def render_airing_notification(payload: dict[str, Any]) -> Any:
    user_ids = payload.get("at_user_ids") or []
    title = payload.get("display_title", "未知")
    episode = payload.get("episode_label", "?")
    summary = f"[预计放送] {title} 第{episode}集 即将播出"
    chain: list[Any] = []
    for user_id in user_ids:
        chain.append(_at_component(user_id))
    chain.append(_plain_component(summary))
    return _message_chain(chain)


def render_release_batch(
    payload: dict[str, Any],
    *,
    proactive_action_links_enabled: bool = False,
    proactive_action_link_sources: Iterable[str] = ("bilibili",),
) -> Any:
    text = format_release_notification(
        payload,
        proactive_action_links_enabled=proactive_action_links_enabled,
        proactive_action_link_sources=proactive_action_link_sources,
    )
    user_ids = payload.get("at_user_ids") or []
    chain: list[Any] = []
    for user_id in user_ids:
        chain.append(_at_component(user_id))
    chain.append(_plain_component(str(text)))
    return _message_chain(chain)


__all__ = [
    "RenderedReply",
    "render_airing_notification",
    "render_release_batch",
    "render_reply",
    "reply_to_event_result",
]
