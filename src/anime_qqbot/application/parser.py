"""Parse the fixed command prefix into an Intent (Task 6).

The fixed command surface from the spec:

* /番剧 今天 [YYYY-MM-DD]
* /番剧 本周
* /番剧 季度 [年份] [冬|春|夏|秋]
* /番剧 搜索 <关键词>
* /番剧 详情 <内部 ID|关键词>
* /番剧 下次 <内部 ID|关键词>
* /番剧 订阅 <内部 ID|关键词>
* /番剧 取消订阅 <内部 ID|关键词>
* /番剧 我的订阅
* /番剧 订阅设置 <内部 ID> [语言=...] [字幕组=...] [分辨率=...]
* /番剧 状态
* /番剧 映射待处理 (admin only)

The parser returns an `Intent` with `query` or `anime_id` populated
when the input is an internal ID. Multi-candidate results are not the
parser's concern; the application layer must ask the user to pick by
internal ID.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from anime_qqbot.application.intents import Intent, IntentKind

_SEASON_NAMES: dict[str, str] = {
    "冬": "winter",
    "春": "spring",
    "夏": "summer",
    "秋": "autumn",
}

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_YEAR_RE = re.compile(r"^(\d{4})$")
_INTERNAL_ID_RE = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")


@dataclass(frozen=True)
class ParseFailure:
    reason: str


def is_internal_id(token: str) -> bool:
    return bool(_INTERNAL_ID_RE.match(token.strip()))


def parse_fixed_command(content: str) -> Intent | ParseFailure:
    """Parse one of the spec's fixed commands.

    Returns either an `Intent` or a `ParseFailure` describing why the
    message could not be mapped to a known command.
    """

    raw = content.strip()
    body = raw
    if raw.startswith("/番剧"):
        body = raw[len("/番剧") :].strip()
    elif raw.startswith("番剧"):
        body = raw[len("番剧") :].strip()
    else:
        return ParseFailure("not a fixed command")

    if not body:
        return ParseFailure("missing subcommand")

    parts = body.split()
    head, rest = parts[0], parts[1:]
    tail = " ".join(rest)

    if head == "今天":
        date_iso = _parse_date(tail)
        if isinstance(date_iso, ParseFailure):
            return date_iso
        return Intent(
            kind=IntentKind.TODAY,
            query=date_iso if date_iso else None,
            raw=raw,
        )

    if head == "本周":
        return Intent(kind=IntentKind.WEEK, raw=raw)

    if head == "季度":
        season_year, season_name, failure = _parse_season(rest)
        if failure is not None:
            return failure
        return Intent(
            kind=IntentKind.SEASON,
            season_year=season_year,
            season_name=season_name,
            raw=raw,
        )

    if head == "搜索":
        if not tail:
            return ParseFailure("搜索 需要关键词")
        return Intent(kind=IntentKind.SEARCH, query=tail, raw=raw)

    if head == "详情":
        if not tail:
            return ParseFailure("详情 需要内部 ID 或关键词")
        return Intent(
            kind=IntentKind.DETAIL,
            query=None if is_internal_id(tail) else tail,
            anime_id=tail if is_internal_id(tail) else None,
            raw=raw,
        )

    if head == "下次":
        if not tail:
            return ParseFailure("下次 需要内部 ID 或关键词")
        return Intent(
            kind=IntentKind.NEXT,
            query=None if is_internal_id(tail) else tail,
            anime_id=tail if is_internal_id(tail) else None,
            raw=raw,
        )

    if head == "订阅":
        if not tail:
            return ParseFailure("订阅 需要内部 ID 或关键词")
        return Intent(
            kind=IntentKind.SUBSCRIBE,
            query=None if is_internal_id(tail) else tail,
            anime_id=tail if is_internal_id(tail) else None,
            raw=raw,
        )

    if head == "取消订阅":
        if not tail:
            return ParseFailure("取消订阅 需要内部 ID 或关键词")
        return Intent(
            kind=IntentKind.UNSUBSCRIBE,
            query=None if is_internal_id(tail) else tail,
            anime_id=tail if is_internal_id(tail) else None,
            raw=raw,
        )

    if head == "我的订阅":
        return Intent(kind=IntentKind.MY_SUBSCRIPTIONS, raw=raw)

    if head == "订阅设置":
        if not rest:
            return ParseFailure("订阅设置 需要内部 ID")
        anime_id = rest[0]
        if not is_internal_id(anime_id):
            return ParseFailure("订阅设置 需要内部 ID")
        language, groups, _resolutions, failure = _parse_settings(rest[1:])
        if failure is not None:
            return failure
        return Intent(
            kind=IntentKind.SUBSCRIPTION_SETTINGS,
            anime_id=anime_id,
            language=language,
            subtitle_groups=groups,
            raw=raw,
        )

    if head == "状态":
        return Intent(kind=IntentKind.STATUS, raw=raw)

    if head == "映射待处理":
        return Intent(kind=IntentKind.MAPPING_PENDING, raw=raw)

    if head == "帮助" or head == "help":
        return Intent(kind=IntentKind.HELP, raw=raw)

    return ParseFailure(f"unknown subcommand: {head}")


def _parse_date(token: str) -> str | ParseFailure:
    token = token.strip()
    if not token:
        return ""
    match = _DATE_RE.match(token)
    if match is None:
        return ParseFailure("今天 日期格式应为 YYYY-MM-DD")
    year, month, day = match.groups()
    try:
        # Validate that month and day are real calendar values.
        from datetime import date as _date

        _date(int(year), int(month), int(day))
    except ValueError:
        return ParseFailure("今天 日期不合法")
    return token


def _parse_season(parts: list[str]) -> tuple[int | None, str | None, ParseFailure | None]:
    if not parts:
        return None, None, ParseFailure("季度 需要 [年份] [冬|春|夏|秋]")
    if len(parts) == 1:
        # /番剧 季度 夏  -> current year, that season
        name = parts[0]
        if name not in _SEASON_NAMES:
            return None, None, ParseFailure("季度 名称必须是 冬/春/夏/秋")
        from datetime import UTC, datetime

        return datetime.now(UTC).year, _SEASON_NAMES[name], None
    if len(parts) == 2:
        year_str, name = parts
        if not _YEAR_RE.match(year_str):
            return None, None, ParseFailure("季度 年份必须是 4 位数字")
        if name not in _SEASON_NAMES:
            return None, None, ParseFailure("季度 名称必须是 冬/春/夏/秋")
        return int(year_str), _SEASON_NAMES[name], None
    return None, None, ParseFailure("季度 参数过多")


def _parse_settings(
    parts: list[str],
) -> tuple[str | None, tuple[str, ...], tuple[str, ...], ParseFailure | None]:
    language: str | None = None
    groups: tuple[str, ...] = ()
    resolutions: tuple[str, ...] = ()
    for part in parts:
        if "=" not in part:
            return None, (), (), ParseFailure("订阅设置 必须使用 key=value 形式")
        key, value = part.split("=", 1)
        if key == "语言":
            language = value
        elif key == "字幕组":
            groups = tuple(value.split(","))
        elif key == "分辨率":
            resolutions = tuple(value.split(","))
        else:
            return None, (), (), ParseFailure(f"订阅设置 不支持的字段: {key}")
    return language, groups, resolutions, None


__all__ = ["ParseFailure", "is_internal_id", "parse_fixed_command"]
