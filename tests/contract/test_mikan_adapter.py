from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from anime_qqbot.catalog.adapters.http_policy import ProviderError, ProviderErrorKind
from anime_qqbot.resources.adapters.mikan import MikanClient

RSS_URL = "https://mikanani.me/RSS/Bangumi?bangumiId=123"
RSS_BODY = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <item>
      <guid>release-1</guid>
      <title>[Group A] Example [01][1080p][简日]</title>
      <pubDate>Tue, 28 Jul 2026 12:00:00 +0000</pubDate>
      <link>https://mikanani.me/Home/Episode/release-1</link>
    </item>
  </channel>
</rss>
"""


@respx.mock
async def test_fetch_feed_returns_items_and_conditional_metadata() -> None:
    route = respx.get(RSS_URL).mock(
        return_value=httpx.Response(
            200,
            text=RSS_BODY,
            headers={"ETag": '"feed-v2"', "Last-Modified": "Tue, 28 Jul 2026 12:01:00 GMT"},
        )
    )
    async with MikanClient() as client:
        result = await client.fetch_feed(
            RSS_URL,
            etag='"feed-v1"',
            last_modified="Tue, 28 Jul 2026 11:00:00 GMT",
        )

    request = route.calls.last.request
    assert request.headers["if-none-match"] == '"feed-v1"'
    assert request.headers["if-modified-since"] == "Tue, 28 Jul 2026 11:00:00 GMT"
    assert result.not_modified is False
    assert result.etag == '"feed-v2"'
    assert result.last_modified == "Tue, 28 Jul 2026 12:01:00 GMT"
    assert result.items[0].guid == "release-1"
    assert result.items[0].pub_date == datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    assert result.items[0].page_url == "https://mikanani.me/Home/Episode/release-1"


@respx.mock
async def test_not_modified_preserves_existing_cursor() -> None:
    respx.get(RSS_URL).mock(return_value=httpx.Response(304))
    async with MikanClient() as client:
        result = await client.fetch_feed(
            RSS_URL,
            etag='"feed-v1"',
            last_modified="Tue, 28 Jul 2026 11:00:00 GMT",
        )

    assert result.not_modified is True
    assert result.items == ()
    assert result.etag == '"feed-v1"'
    assert result.last_modified == "Tue, 28 Jul 2026 11:00:00 GMT"


@respx.mock
async def test_unsafe_xml_is_rejected() -> None:
    unsafe = """<?xml version="1.0"?>
<!DOCTYPE rss [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<rss><channel><item><guid>1</guid><title>&xxe;</title>
<pubDate>Tue, 28 Jul 2026 12:00:00 +0000</pubDate></item></channel></rss>"""
    respx.get(RSS_URL).mock(return_value=httpx.Response(200, text=unsafe))

    async with MikanClient() as client:
        with pytest.raises(ProviderError) as exc_info:
            await client.fetch_feed(RSS_URL)

    assert exc_info.value.kind is ProviderErrorKind.INVALID_RESPONSE


async def test_private_or_non_anime_feed_url_is_rejected_before_network() -> None:
    async with MikanClient() as client:
        with pytest.raises(ProviderError) as exc_info:
            await client.fetch_feed("https://mikanani.me/RSS/MyBangumi?token=private-user-token")

    assert exc_info.value.kind is ProviderErrorKind.PERMANENT
