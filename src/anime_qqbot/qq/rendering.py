# ruff: noqa: RUF001

from zoneinfo import ZoneInfo

from anime_qqbot.catalog.models import AiringOccurrence, AnimeDetail, AnimeSummary, CatalogListing
from anime_qqbot.qq.contracts import MessageButton, OutboundMessage

HELP_TEXT = """追番机器人命令：
今日番剧 [YYYY-MM-DD]｜本周番剧｜季度番剧 [年份] 春/夏/秋/冬
搜索 <关键词>｜番剧 <ID|关键词>｜下次更新 <ID|关键词>
群内：订阅 <ID|关键词>｜取消订阅 <ID|关键词>｜我的订阅
群管理员可配置每日/每周推送、时区并查看推送状态。"""


def render_listing(title: str, listing: CatalogListing, timezone: ZoneInfo) -> OutboundMessage:
    if not listing.subjects:
        return OutboundMessage(f"{title}\n暂无番剧数据。")
    occurrences = {item.subject_id: item for item in listing.occurrences}
    lines = [title]
    for subject in listing.subjects:
        if subject.nsfw:
            continue
        occurrence = occurrences.get(subject.subject_id)
        schedule = _schedule(occurrence, timezone) if occurrence else ""
        lines.append(f"• {subject.title}（Bangumi {subject.subject_id}）{schedule}")
    if listing.freshness.is_stale:
        lines.append("⚠ 数据可能已陈旧，请以实际播出为准。")
    return OutboundMessage("\n".join(lines))


def render_search(results: list[AnimeSummary]) -> OutboundMessage:
    safe = [item for item in results if not item.nsfw]
    if not safe:
        return OutboundMessage("没有找到符合条件的番剧。")
    lines = ["搜索结果："] + [
        f"{index}. {item.title}（Bangumi {item.subject_id}）" for index, item in enumerate(safe, 1)
    ]
    buttons = tuple(MessageButton(item.title[:20], f"番剧 {item.subject_id}") for item in safe[:5])
    return OutboundMessage("\n".join(lines), buttons=buttons)


def render_detail(detail: AnimeDetail) -> OutboundMessage:
    if detail.nsfw:
        return OutboundMessage("该条目不可展示。")
    lines = [f"{detail.title}（Bangumi {detail.subject_id}）"]
    if detail.air_date:
        lines.append(f"首播：{detail.air_date.isoformat()}")
    if detail.score is not None:
        lines.append(f"评分：{detail.score:.1f}")
    if detail.total_episodes:
        lines.append(f"话数：{detail.total_episodes}")
    if detail.summary:
        lines.append(detail.summary[:300])
    return OutboundMessage("\n".join(lines))


def render_next(
    detail: AnimeDetail, occurrence: AiringOccurrence | None, timezone: ZoneInfo
) -> OutboundMessage:
    if occurrence is None:
        return OutboundMessage(f"{detail.title} 暂无下一次预计放送数据。")
    episode = f"第 {occurrence.episode} 话" if occurrence.episode else "新内容"
    return OutboundMessage(
        f"{detail.title} {episode}预计放送：{_schedule(occurrence, timezone).strip()}\n"
        "该时间是数据源预计放送时间，不代表字幕或国内平台资源已上线。"
    )


def _schedule(occurrence: AiringOccurrence, timezone: ZoneInfo) -> str:
    local = occurrence.in_timezone(timezone)
    if local is None:
        return f" — 预计 {occurrence.air_date.isoformat()} 放送"
    return f" — 预计 {local:%Y-%m-%d %H:%M}（{timezone.key}）放送"
