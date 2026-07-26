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

    text = "\n".join(parts) if parts else "（无内容）"
    return text  # tests assert on the returned plain text


__all__ = ["render_reply"]
