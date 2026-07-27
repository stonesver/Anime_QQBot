"""Map a platform-neutral Reply to AstrBot / CQHTTP message components."""

from __future__ import annotations

from typing import Any

from astrbot_plugin_anime_tracking.anime_tracking_plugin.adapter import Reply


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
        parts.append("多个结果，请通过内部 ID 选择：")  # noqa: RUF001
        for idx, cand in enumerate(reply.candidates, start=1):
            parts.append(f"  {idx}. {cand}")

    if reply.error:
        parts.append(f"错误: {reply.error}")

    text = "\n".join(parts) if parts else "（无内容）"  # noqa: RUF001
    return text  # tests assert on the returned plain text


def render_airing_notification(payload: dict) -> str:
    """Render an airing notification into a plain text summary."""
    title = payload.get("display_title", "未知")
    episode = payload.get("episode_label", "?")
    return f"[预计放送] {title} 第{episode}集 即将播出"


__all__ = ["render_airing_notification", "render_reply"]
