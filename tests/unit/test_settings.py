from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from anime_qqbot.settings import AdminIdentity, Settings


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://anime:anime@localhost/anime",
        "bangumi_user_agent": "anime-qqbot/test@example.com",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_settings_expose_safe_operational_defaults() -> None:
    settings = make_settings()

    assert settings.default_timezone == "Asia/Shanghai"
    assert settings.catalog_cache_ttl_seconds == 3600
    assert settings.bangumi_data_sync_seconds == 21600
    assert settings.worker_scan_seconds == 30
    assert settings.daily_compensation_seconds == 7200
    assert settings.weekly_compensation_seconds == 86400
    assert settings.processed_event_retention_days == 7
    assert settings.delivery_retention_days == 90
    assert settings.qq_event_transport == "webhook"


def test_bot_credentials_are_required_only_when_bot_runtime_starts() -> None:
    settings = make_settings()

    with pytest.raises(ValueError, match="QQ_APP_ID and QQ_APP_SECRET"):
        settings.require_bot_credentials()

    configured = make_settings(qq_app_id="123", qq_app_secret=SecretStr("secret"))
    assert configured.require_bot_credentials() == ("123", "secret")


def test_bootstrap_admin_identities_parse_group_and_member_pairs() -> None:
    settings = make_settings(bootstrap_admin_identities="group-a:member-a, group-b:member-b")

    assert settings.bootstrap_admin_identities == (
        AdminIdentity(group_openid="group-a", member_openid="member-a"),
        AdminIdentity(group_openid="group-b", member_openid="member-b"),
    )


def test_invalid_admin_identity_is_rejected() -> None:
    with pytest.raises(ValidationError, match="group_openid:member_openid"):
        make_settings(bootstrap_admin_identities="not-a-pair")


def test_env_file_path_is_not_part_of_settings_state(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL=postgresql+asyncpg://anime:anime@localhost/anime\n"
        "BANGUMI_USER_AGENT=anime-qqbot/test@example.com\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.database_url.endswith("/anime")
