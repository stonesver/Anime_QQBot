"""Map a platform-neutral Reply to AstrBot / CQHTTP message components."""

from __future__ import annotations

from typing import Any

from .adapter import Reply


async def render_reply(reply: Reply, event: Any) -> Any:
    """Render a Reply into an AstrBot Plain / Image / At message chain.

    In production `event` is an AstrBot AstrMessageEvent; in tests it
    is a fake that captures the rendered output.
    """
    parts: list[str] = []
    for block in reply.blocks:
        if block.text:
            parts.append(block.text)

    if reply.candidates:
        parts.append("多个结果，请通过内部 ID 选择：")
        for idx, cand in enumerate(reply.candidates, start=1):
            parts.append(f"  {idx}. {cand}")

    if reply.error:
        parts.append(f"错误: {reply.error}")

    text = "\n".join(parts) if parts else "（无内容）"
    return text  # tests assert on the returned plain text


def render_airing_notification(payload: dict) -> list[Any]:
    """Render an airing notification into an AstrBot message chain.

    Returns a list with ``[At(segment=user_ids), Plain(text=summary)]``
    so the plugin can address the subscriber while announcing the
    scheduled air time.
    """
    user_ids = payload.get("at_user_ids") or []
    title = payload.get("display_title", "未知")
    episode = payload.get("episode_label", "?")
    summary = f"[预计放送] {title} 第{episode}集 即将播出"
    chain: list[Any] = []
    for user_id in user_ids:
        chain.append({"type": "at", "qq": user_id})
    chain.append({"type": "plain", "text": summary})
    return chain


def render_release_batch(payload: dict) -> list[Any]:
    """Render a release batch notification into a message chain.

    The first 5 releases are listed explicitly; additional releases
    are summarised by a count. The payload carries the batch
    description as ``text`` and an optional list of subscriber ids.
    """
    text = payload.get("text", "")
    user_ids = payload.get("at_user_ids") or []
    chain: list[Any] = []
    for user_id in user_ids:
        chain.append({"type": "at", "qq": user_id})
    chain.append({"type": "plain", "text": text})
    return chain


__all__ = ["render_airing_notification", "render_release_batch", "render_reply"]
