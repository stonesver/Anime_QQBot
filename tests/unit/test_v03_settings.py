from __future__ import annotations

import pytest
from pydantic import ValidationError

from anime_qqbot.settings import Settings


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://anime:anime@localhost/anime",
        "bangumi_user_agent": "anime-qqbot/test@example.com",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_v03_release_switches_are_safe_by_default() -> None:
    settings = _settings()

    assert settings.interaction_gateway_enabled is False
    assert settings.send_governor_enabled is False
    assert settings.admin_page_writes_enabled is False


def test_send_governor_defaults_match_release_policy() -> None:
    settings = _settings()

    assert settings.send_global_interval_seconds == 2.5
    assert settings.send_global_burst == 2
    assert settings.send_group_interval_seconds == 5
    assert settings.send_user_interval_seconds == 5
    assert settings.send_user_limit_per_minute == 10
    assert settings.send_proactive_group_interval_seconds == 60
    assert settings.send_proactive_group_limit_per_10_minutes == 3


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("send_global_interval_seconds", 0),
        ("send_global_burst", 0),
        ("send_group_interval_seconds", -1),
        ("send_user_limit_per_minute", 0),
        ("send_proactive_group_limit_per_10_minutes", 101),
    ],
)
def test_send_governor_limits_are_bounded(name: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _settings(**{name: value})
