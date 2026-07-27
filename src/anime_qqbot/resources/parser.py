"""Mikan release title parser (Task 23).

Parses raw Mikan RSS titles into structured fields: episode_label,
subtitle groups, language, resolutions, spec tags. The parser is pure
computation, length-bounded, and versioned for offline replay.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PARSER_VERSION: str = "v1"


@dataclass(frozen=True)
class ParsedRelease:
    episode_label: str | None
    subtitle_groups: tuple[str, ...]
    language: str | None
    resolutions: tuple[str, ...]
    spec_tags: tuple[str, ...]
    parser_version: str
    parse_warnings: tuple[str, ...]


# Common subtitle group names and resolution patterns
_GROUP_RE = re.compile(r"\[([^\]]+)\]")
_RES_RE = re.compile(r"\b(\d{3,4}p)\b", re.IGNORECASE)
_EP_RE = re.compile(r"(?:[第]?\s*(\d{1,3})\s*(?:話|话|集|ep)|\[(\d{1,3})[^\]]*\])", re.IGNORECASE)
_SPECIAL_RE = re.compile(r"\b(OVA|OAD|ONA|SP|剧场版|总集篇|分割(?:\d+))\b", re.IGNORECASE)
_LANG_HINT = re.compile(r"\[?(简|繁|chs|cht|sc|tc)[^\]]*\]?", re.IGNORECASE)


def parse_release_title(raw_title: str) -> ParsedRelease:
    if len(raw_title) > 1024:
        return ParsedRelease(
            episode_label=None,
            subtitle_groups=(),
            language=None,
            resolutions=(),
            spec_tags=(),
            parser_version=PARSER_VERSION,
            parse_warnings=("title_too_long",),
        )

    # Extract [ ... ] blocks as candidate subtitles.
    groups: list[str] = []
    clean: list[str] = []
    pos = 0
    for m in _GROUP_RE.finditer(raw_title):
        text = m.group(1).strip()
        # If the block looks like a subtitle group (no digits, short),
        # treat it as such.
        if len(text) <= 32 and not text.isdigit():
            groups.append(text)
        else:
            clean.append(raw_title[pos : m.end()])
        pos = m.end()
    remaining = raw_title[pos:]
    if remaining:
        clean.append(remaining)

    # Resolutions from the full title
    resolutions: list[str] = []
    seen_res = set()
    for m in _RES_RE.finditer(raw_title):
        val = m.group(1).lower()
        if val not in seen_res:
            resolutions.append(val)
            seen_res.add(val)

    # Episode
    ep_m = _EP_RE.search(raw_title)
    episode_label = None
    if ep_m:
        for g in ep_m.groups():
            if g is not None:
                episode_label = g
                break

    # Special tags
    spec_tags = list({m.group(0) for m in _SPECIAL_RE.finditer(raw_title)})

    # Language hints
    lang_m = _LANG_HINT.search(raw_title)
    language: str | None = None
    if lang_m:
        v = lang_m.group(1).lower()
        language = (
            "chs" if v in {"简", "chs", "sc"} else "cht" if v in {"繁", "cht", "tc"} else None
        )

    warnings: list[str] = []
    if episode_label is None:
        warnings.append("unknown_episode")

    return ParsedRelease(
        episode_label=episode_label,
        subtitle_groups=tuple(groups),
        language=language,
        resolutions=tuple(resolutions),
        spec_tags=tuple(spec_tags),
        parser_version=PARSER_VERSION,
        parse_warnings=tuple(warnings),
    )


__all__ = ["PARSER_VERSION", "ParsedRelease", "parse_release_title"]
