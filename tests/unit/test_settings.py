"""Minimal settings tests — QQ/AdminIdentity fields removed in v0.2.0."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from anime_qqbot.settings import Settings


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://anime:anime@localhost/anime",
        "bangumi_user_agent": "anime-qqbot/test@example.com",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_database_url_is_required() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, bangumi_user_agent="test/1.0")


def test_bangumi_user_agent_must_satisfy_min_length() -> None:
    with pytest.raises(ValidationError):
        make_settings(bangumi_user_agent="ab")


def test_default_values() -> None:
    settings = make_settings()

    assert settings.app_env == "development"
    assert settings.bangumi_api_base_url == "https://api.bgm.tv"
    assert settings.bangumi_access_token is None
    assert settings.default_timezone == "Asia/Shanghai"
    assert settings.animeschedule_enabled is False
    assert settings.animeschedule_token is None
    assert settings.animeschedule_query_budget == 12
    assert settings.animeschedule_priority_window_days == 7
    assert settings.animeschedule_empty_cooldown_hours == 168
    assert settings.animeschedule_error_cooldown_hours == 168


def test_bangumi_access_token_stored_as_secret() -> None:
    settings = make_settings(bangumi_access_token="my-token")

    assert settings.bangumi_access_token == SecretStr("my-token")


def test_animeschedule_token_stored_as_secret() -> None:
    settings = make_settings(animeschedule_token="application-token")

    assert settings.animeschedule_token == SecretStr("application-token")


def test_animeschedule_cannot_be_enabled_without_token() -> None:
    with pytest.raises(ValidationError, match="ANIMESCHEDULE_TOKEN"):
        make_settings(animeschedule_enabled=True)


def test_bangumi_fallback_urls_parsed_from_comma_string() -> None:
    settings = make_settings(
        bangumi_api_fallback_urls="https://mirror1.example,https://mirror2.example"
    )

    assert settings.bangumi_api_fallback_urls == (
        "https://mirror1.example",
        "https://mirror2.example",
    )


def test_bangumi_fallback_urls_dedup_base_url() -> None:
    settings = make_settings(
        bangumi_api_base_url="https://api.bgm.tv",
        bangumi_api_fallback_urls="https://api.bgm.tv,https://mirror.example",
    )

    assert settings.bangumi_api_fallback_urls == ("https://mirror.example",)


def test_catalog_cache_defaults() -> None:
    settings = make_settings()

    assert settings.catalog_cache_ttl_seconds == 3600
    assert settings.bangumi_data_sync_seconds == 21600
    assert settings.worker_scan_seconds == 30
