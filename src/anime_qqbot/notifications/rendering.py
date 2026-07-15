# ruff: noqa: RUF001

from zoneinfo import ZoneInfo

from anime_qqbot.notifications.module import NotificationAudience
from anime_qqbot.qq.contracts import OutboundMessage


def render_notifications(
    items: list[NotificationAudience], timezone: ZoneInfo, max_chars: int = 1800
) -> list[OutboundMessage]:
    blocks: list[str] = []
    mentions: list[tuple[str, ...]] = []
    for item in items:
        when = item.air_date
        if item.air_at:
            when = item.air_at.astimezone(timezone).strftime("%Y-%m-%d %H:%M")
        blocks.append(f"{item.title}\n预计放送: {when} ({timezone.key})")
        mentions.append(item.member_openids)
    chunks: list[OutboundMessage] = []
    text = ""
    current_mentions: set[str] = set()
    for block, audience in zip(blocks, mentions, strict=True):
        candidate = f"{text}\n\n{block}" if text else block
        if text and len(candidate) > max_chars:
            chunks.append(OutboundMessage(text, mentions=tuple(sorted(current_mentions))))
            text, current_mentions = block, set(audience)
        else:
            text = candidate
            current_mentions.update(audience)
    if text:
        chunks.append(
            OutboundMessage(
                text + "\n\n时间为预计放送，实际上线可能延迟。",
                mentions=tuple(sorted(current_mentions)),
            )
        )
    total = len(chunks)
    return (
        [
            OutboundMessage(f"[{index}/{total}]\n{chunk.text}", mentions=chunk.mentions)
            for index, chunk in enumerate(chunks, 1)
        ]
        if total > 1
        else chunks
    )
