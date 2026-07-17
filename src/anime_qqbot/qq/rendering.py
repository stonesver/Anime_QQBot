# ruff: noqa: RUF001

from dataclasses import replace
from enum import StrEnum
from math import ceil
from zoneinfo import ZoneInfo

from anime_qqbot.catalog.models import (
    AiringOccurrence,
    AnimeDetail,
    AnimeSummary,
    CatalogFreshness,
    CatalogListing,
)
from anime_qqbot.qq.contracts import MessageButton, OutboundMessage


class PresentationMode(StrEnum):
    CARD = "card"
    STRUCTURED = "structured"
    COMPACT = "compact"


def select_presentation_mode(count: int) -> PresentationMode:
    if count <= 20:
        return PresentationMode.CARD
    if count <= 50:
        return PresentationMode.STRUCTURED
    return PresentationMode.COMPACT


HELP_TEXT = """追番机器人命令：
今日番剧 [YYYY-MM-DD]｜本周番剧｜季度番剧 [年份] 春/夏/秋/冬
搜索 <关键词>｜番剧 <ID|关键词>｜下次更新 <ID|关键词>
群内：订阅 <ID|关键词>｜取消订阅 <ID|关键词>｜我的订阅
群管理员可配置每日/每周推送、时区并查看推送状态。"""


def render_help() -> OutboundMessage:
    markdown = """# 📺 追番机器人

## 查询番剧
- 今日番剧 [YYYY-MM-DD]
- 本周番剧
- 季度番剧 [年份] 春/夏/秋/冬
- 搜索「关键词」
- 番剧「ID 或关键词」
- 下次更新「ID 或关键词」

## 群内订阅
- 订阅「ID 或关键词」
- 取消订阅「ID 或关键词」
- 我的订阅

## 群管理
群主或管理员可以配置每日/每周推送、时区并查看推送状态。"""
    return OutboundMessage(
        HELP_TEXT,
        markdown=markdown,
        buttons=(
            MessageButton("今日番剧", "今日番剧"),
            MessageButton("本周番剧", "本周番剧"),
            MessageButton("季度番剧", "季度番剧"),
            MessageButton("我的订阅", "我的订阅"),
        ),
    )


def render_subscription_status(title: str, change: str) -> OutboundMessage:
    headings = {
        "added": "✅ 订阅成功",
        "restored": "✅ 已恢复订阅",
        "unchanged": "ℹ️ 已经订阅",
        "disabled": "✅ 已取消订阅",
        "not_found": "ℹ️ 当前没有订阅",
    }
    labels = {
        "added": "已添加",
        "restored": "已恢复",
        "unchanged": "已订阅",
        "disabled": "已取消",
        "not_found": "未订阅",
    }
    heading = headings.get(change, "ℹ️ 订阅状态")
    return OutboundMessage(
        f"{title}：{change}",
        markdown=(
            f"# {heading}\n\n**{_escape_markdown(title)}**\n\n状态：{labels.get(change, change)}"
        ),
        buttons=(MessageButton("我的订阅", "我的订阅"),),
    )


def render_listing(
    title: str,
    listing: CatalogListing,
    timezone: ZoneInfo,
    *,
    command: str = "",
    page: int = 1,
    force_compact: bool = False,
    image_proxy_base_url: str | None = None,
) -> OutboundMessage:
    subjects = tuple(subject for subject in listing.subjects if not subject.nsfw)
    if not subjects:
        return OutboundMessage(f"{title}\n暂无番剧数据。")
    mode = PresentationMode.COMPACT if force_compact else select_presentation_mode(len(subjects))
    page_size = {
        PresentationMode.CARD: 5,
        PresentationMode.STRUCTURED: 15,
        PresentationMode.COMPACT: 30,
    }[mode]
    total_pages = max(1, ceil(len(subjects) / page_size))
    current_page = min(max(page, 1), total_pages)
    starts_at = (current_page - 1) * page_size
    visible = subjects[starts_at : starts_at + page_size]
    occurrences = {item.subject_id: item for item in listing.occurrences}

    lines = [title]
    for subject in visible:
        occurrence = occurrences.get(subject.subject_id)
        schedule = _schedule(occurrence, timezone) if occurrence else ""
        lines.append(f"• {subject.title}（Bangumi {subject.subject_id}）{schedule}")
    if listing.freshness.is_stale:
        lines.append("⚠ 数据可能已陈旧，请以实际播出为准。")
    lines.append(f"第 {current_page}/{total_pages} 页 · 共 {len(subjects)} 部")

    fallback_markdown: str | None = None
    if mode is PresentationMode.CARD:
        markdown = _render_card_markdown(
            title,
            visible,
            occurrences,
            timezone,
            current_page,
            total_pages,
            len(subjects),
            listing.freshness.is_stale,
            image_proxy_base_url=image_proxy_base_url,
        )
        fallback_markdown = _render_card_markdown(
            title,
            visible,
            occurrences,
            timezone,
            current_page,
            total_pages,
            len(subjects),
            listing.freshness.is_stale,
            include_images=False,
        )
    elif mode is PresentationMode.STRUCTURED:
        markdown = _render_structured_markdown(
            title,
            visible,
            occurrences,
            timezone,
            current_page,
            total_pages,
            len(subjects),
            listing.freshness.is_stale,
        )
    else:
        markdown = _render_compact_markdown(
            title,
            visible,
            occurrences,
            timezone,
            starts_at,
            current_page,
            total_pages,
            len(subjects),
            listing.freshness.is_stale,
        )
    return OutboundMessage(
        "\n".join(lines),
        markdown=markdown,
        fallback_markdown=fallback_markdown,
        buttons=_listing_buttons(command, current_page, total_pages, mode),
    )


def _render_card_markdown(
    title: str,
    subjects: tuple[AnimeSummary, ...],
    occurrences: dict[int, AiringOccurrence],
    timezone: ZoneInfo,
    page: int,
    total_pages: int,
    total_subjects: int,
    stale: bool,
    *,
    include_images: bool = True,
    image_proxy_base_url: str | None = None,
) -> str:
    lines = [
        f"# {_escape_markdown(title)}",
        f"第 {page}/{total_pages} 页 · 共 {total_subjects} 部 · 时间按 {timezone.key}",
    ]
    for subject in subjects:
        if (
            include_images
            and subject.image_url
            and subject.image_url.startswith(("https://", "http://"))
        ):
            alt = subject.title.replace("[", "").replace("]", "")
            cover_url = _cover_url(subject.subject_id, subject.image_url, image_proxy_base_url)
            lines.extend(["", f"![{alt} #200px #112px]({cover_url})"])
        lines.extend(["", f"## {_escape_markdown(subject.title)}"])
        occurrence = occurrences.get(subject.subject_id)
        if occurrence:
            local = occurrence.in_timezone(timezone)
            when = (
                f"预计 {local:%Y-%m-%d %H:%M} 放送"
                if local
                else f"预计 {occurrence.air_date.isoformat()} 放送"
            )
            episode = f" · 第 {occurrence.episode} 话" if occurrence.episode else ""
            lines.append(f"**{when}**{episode}")
        elif subject.air_date:
            lines.append(f"首播：{subject.air_date.isoformat()}")
        lines.extend([f"Bangumi {subject.subject_id}", "", "***"])
    if stale:
        lines.extend(["", "> ⚠ 数据可能已陈旧，请以实际播出为准。"])
    return "\n".join(lines)


def _listing_buttons(
    command: str,
    page: int,
    total_pages: int,
    mode: PresentationMode,
) -> tuple[MessageButton, ...]:
    if not command:
        return ()
    buttons: list[MessageButton] = []
    if page > 1:
        buttons.append(MessageButton("上一页", f"{command} --page={page - 1}"))
    if page < total_pages:
        buttons.append(MessageButton("下一页", f"{command} --page={page + 1}"))
    if mode is PresentationMode.CARD:
        buttons.append(MessageButton("切换精简列表", f"{command} --view=compact"))
    return tuple(buttons)


def _render_structured_markdown(
    title: str,
    subjects: tuple[AnimeSummary, ...],
    occurrences: dict[int, AiringOccurrence],
    timezone: ZoneInfo,
    page: int,
    total_pages: int,
    total_subjects: int,
    stale: bool,
) -> str:
    lines = [f"# {_escape_markdown(title)}", f"时间按 {timezone.key}"]
    current_group = ""
    weekdays = "一二三四五六日"
    for subject in subjects:
        occurrence = occurrences.get(subject.subject_id)
        local = occurrence.in_timezone(timezone) if occurrence else None
        airing_date = (
            local.date() if local else occurrence.air_date if occurrence else subject.air_date
        )
        group = (
            f"周{weekdays[airing_date.weekday()]} · {airing_date:%m/%d}"
            if airing_date
            else "日期待定"
        )
        if group != current_group:
            lines.extend(["", f"## {group}"])
            current_group = group
        time = f"{local:%H:%M}" if local else "时间待定"
        lines.append(
            f"- **{time}** {_escape_markdown(subject.title)} · Bangumi {subject.subject_id}"
        )
    lines.extend(["", f"第 {page}/{total_pages} 页 · 共 {total_subjects} 部"])
    if stale:
        lines.extend(["", "> ⚠ 数据可能已陈旧，请以实际播出为准。"])
    return "\n".join(lines)


def _render_compact_markdown(
    title: str,
    subjects: tuple[AnimeSummary, ...],
    occurrences: dict[int, AiringOccurrence],
    timezone: ZoneInfo,
    starts_at: int,
    page: int,
    total_pages: int,
    total_subjects: int,
    stale: bool,
) -> str:
    lines = [f"# {_escape_markdown(title)}", f"时间按 {timezone.key}"]
    for index, subject in enumerate(subjects, starts_at + 1):
        occurrence = occurrences.get(subject.subject_id)
        local = occurrence.in_timezone(timezone) if occurrence else None
        if local:
            when = f"{local:%m/%d %H:%M}"
        elif occurrence:
            when = occurrence.air_date.isoformat()
        elif subject.air_date:
            when = subject.air_date.isoformat()
        else:
            when = "待定"
        lines.append(
            f"{index}. **{when}** {_escape_markdown(subject.title)} · Bangumi {subject.subject_id}"
        )
    lines.extend(["", f"第 {page}/{total_pages} 页 · 共 {total_subjects} 部"])
    if stale:
        lines.extend(["", "> ⚠ 数据可能已陈旧，请以实际播出为准。"])
    return "\n".join(lines)


def _escape_markdown(value: str) -> str:
    escaped = value
    for character in ("\\", "*", "_", "[", "]", "(", ")", "#", ">", "~"):
        escaped = escaped.replace(character, f"\\{character}")
    return escaped


def render_search(
    results: list[AnimeSummary],
    *,
    command: str = "搜索",
    page: int = 1,
    force_compact: bool = False,
    image_proxy_base_url: str | None = None,
) -> OutboundMessage:
    safe = [item for item in results if not item.nsfw]
    if not safe:
        return OutboundMessage("没有找到符合条件的番剧。")
    message = render_listing(
        "搜索结果",
        CatalogListing(
            tuple(safe),
            (),
            CatalogFreshness(None, None, False, False),
        ),
        ZoneInfo("Asia/Shanghai"),
        command=command,
        page=page,
        force_compact=force_compact,
        image_proxy_base_url=image_proxy_base_url,
    )
    mode = PresentationMode.COMPACT if force_compact else select_presentation_mode(len(safe))
    page_size = {
        PresentationMode.CARD: 5,
        PresentationMode.STRUCTURED: 15,
        PresentationMode.COMPACT: 30,
    }[mode]
    total_pages = max(1, ceil(len(safe) / page_size))
    current_page = min(max(page, 1), total_pages)
    starts_at = (current_page - 1) * page_size
    direct = tuple(
        MessageButton(item.title[:20], f"番剧 {item.subject_id}")
        for item in safe[starts_at : starts_at + min(page_size, 5)]
    )
    return replace(message, buttons=direct + message.buttons)


def render_subjects(
    title: str,
    subjects: list[AnimeSummary],
    *,
    command: str,
    page: int = 1,
    force_compact: bool = False,
    image_proxy_base_url: str | None = None,
) -> OutboundMessage:
    return render_listing(
        title,
        CatalogListing(
            tuple(subject for subject in subjects if not subject.nsfw),
            (),
            CatalogFreshness(None, None, False, False),
        ),
        ZoneInfo("Asia/Shanghai"),
        command=command,
        page=page,
        force_compact=force_compact,
        image_proxy_base_url=image_proxy_base_url,
    )


def render_detail(
    detail: AnimeDetail, *, image_proxy_base_url: str | None = None
) -> OutboundMessage:
    if detail.nsfw:
        return OutboundMessage("该条目不可展示。")
    lines = [f"{detail.title}（Bangumi {detail.subject_id}）"]
    markdown = [f"# {_escape_markdown(detail.title)}"]
    if detail.image_url and detail.image_url.startswith(("https://", "http://")):
        alt = detail.title.replace("[", "").replace("]", "")
        cover_url = _cover_url(detail.subject_id, detail.image_url, image_proxy_base_url)
        markdown.extend(["", f"![{alt} #320px #180px]({cover_url})"])
    if detail.air_date:
        lines.append(f"首播：{detail.air_date.isoformat()}")
        markdown.extend(["", f"首播：**{detail.air_date.isoformat()}**"])
    if detail.score is not None:
        lines.append(f"评分：{detail.score:.1f}")
        markdown.append(f"评分：**{detail.score:.1f}**")
    if detail.total_episodes:
        lines.append(f"话数：{detail.total_episodes}")
        markdown.append(f"话数：**{detail.total_episodes}**")
    markdown.append(f"Bangumi {detail.subject_id}")
    if detail.summary:
        lines.append(detail.summary[:300])
        markdown.extend(["", _escape_markdown(detail.summary[:300])])
    return OutboundMessage(
        "\n".join(lines),
        markdown="\n".join(markdown),
        fallback_markdown="\n".join(line for line in markdown if not line.startswith("![")),
        buttons=(MessageButton("下次更新", f"下次更新 {detail.subject_id}"),),
    )


def render_next(
    detail: AnimeDetail,
    occurrence: AiringOccurrence | None,
    timezone: ZoneInfo,
    *,
    image_proxy_base_url: str | None = None,
) -> OutboundMessage:
    if occurrence is None:
        text = f"{detail.title} 暂无下一次预计放送数据。"
        return OutboundMessage(
            text,
            markdown=f"# {_escape_markdown(detail.title)}\n\n暂无下一次预计放送数据。",
            buttons=(MessageButton("查看详情", f"番剧 {detail.subject_id}"),),
        )
    episode = f"第 {occurrence.episode} 话" if occurrence.episode else "新内容"
    when = _schedule(occurrence, timezone).removeprefix(" — ")
    text = (
        f"{detail.title} {episode}预计放送：{_schedule(occurrence, timezone).strip()}\n"
        "该时间是数据源预计放送时间，不代表字幕或国内平台资源已上线。"
    )
    markdown = [f"# {_escape_markdown(detail.title)}"]
    if detail.image_url and detail.image_url.startswith(("https://", "http://")):
        alt = detail.title.replace("[", "").replace("]", "")
        cover_url = _cover_url(detail.subject_id, detail.image_url, image_proxy_base_url)
        markdown.extend(["", f"![{alt} #320px #180px]({cover_url})"])
    markdown.extend(
        [
            "",
            f"## {episode}",
            f"**{when}**",
            "",
            "> 该时间是数据源预计放送时间，不代表字幕或国内平台资源已上线。",
        ]
    )
    return OutboundMessage(
        text,
        markdown="\n".join(markdown),
        fallback_markdown="\n".join(line for line in markdown if not line.startswith("![")),
        buttons=(MessageButton("查看详情", f"番剧 {detail.subject_id}"),),
    )


def _schedule(occurrence: AiringOccurrence, timezone: ZoneInfo) -> str:
    local = occurrence.in_timezone(timezone)
    if local is None:
        return f" — 预计 {occurrence.air_date.isoformat()} 放送"
    return f" — 预计 {local:%Y-%m-%d %H:%M}（{timezone.key}）放送"


def _cover_url(subject_id: int, original_url: str, proxy_base_url: str | None) -> str:
    if proxy_base_url:
        return f"{proxy_base_url.rstrip('/')}/{subject_id}"
    return original_url
