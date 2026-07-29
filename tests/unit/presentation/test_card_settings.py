from __future__ import annotations

import pytest
from pydantic import ValidationError

from anime_qqbot.settings import Settings


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://anime:anime@localhost/anime",
        "bangumi_user_agent": "anime-qqbot/test test@example.com",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_card_asset_defaults() -> None:
    settings = make_settings()

    assert settings.card_asset_root == "/var/lib/anime-qqbot/cards"
    assert settings.card_cache_max_bytes == 314_572_800
    assert settings.card_cache_target_bytes == 283_115_520
    assert settings.poster_download_max_bytes == 8_388_608
    assert settings.poster_decode_max_pixels == 30_000_000
    assert settings.poster_connect_timeout_seconds == 3
    assert settings.poster_total_timeout_seconds == 10


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("card_cache_max_bytes", 0),
        ("card_cache_target_bytes", 0),
        ("poster_download_max_bytes", 0),
        ("poster_decode_max_pixels", 0),
        ("poster_connect_timeout_seconds", 0),
        ("poster_total_timeout_seconds", 0),
    ],
)
def test_card_asset_limits_must_be_positive(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        make_settings(**{field: value})


def test_cache_target_must_be_below_maximum() -> None:
    with pytest.raises(ValidationError):
        make_settings(card_cache_max_bytes=100, card_cache_target_bytes=100)
