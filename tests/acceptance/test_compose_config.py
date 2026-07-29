"""Acceptance tests for v0.2 compose configuration (Task 11)."""

from __future__ import annotations

from pathlib import Path


def test_compose_declares_migration_gate_and_healthchecks() -> None:
    compose = Path("compose.yaml").read_text()

    assert "condition: service_completed_successfully" in compose
    assert compose.count("healthcheck:") >= 2
    assert "postgres-data:/var/lib/postgresql/data" in compose
    assert 'restart: "no"' in compose


def test_five_services_present() -> None:
    compose = Path("compose.yaml").read_text()

    assert "postgres:" in compose
    assert "migrate:" in compose
    assert "worker:" in compose
    assert "napcat:" in compose
    assert "astrbot:" in compose


def test_napcat_uses_reverse_ws_with_token() -> None:
    compose = Path("compose.yaml").read_text()
    entrypoint = Path("scripts/napcat-entrypoint.sh").read_text()

    assert "astrbot:6199/ws" in entrypoint
    assert '"httpServers": [ {' in entrypoint
    assert '"name": "astrbot-status"' in entrypoint
    assert '"port": 3000' in entrypoint
    assert '"enableCors": false' in entrypoint
    assert "ONEBOT_TOKEN" in compose
    assert "ONEBOT_TOKEN must be set" in compose
    assert "BANGUMI_USER_AGENT must be set" in compose
    assert '"token": "\'"${token}"\'"' in entrypoint
    assert "> /app/templates/astrbot.json" in entrypoint
    assert "export MODE=astrbot" in entrypoint
    assert "NAPCAT_ONEBOT_URL: http://napcat:3000" in compose
    assert "NAPCAT_STATUS_POLL_SECONDS: 60" in compose
    assert "3000:3000" not in compose


def test_no_qq_official_services() -> None:
    compose = Path("compose.yaml").read_text()

    assert "QQ_APP_ID" not in compose
    assert "QQ_APP_SECRET" not in compose
    assert "QQ_WEBHOOK_PORT" not in compose


def test_runtime_image_excludes_secrets() -> None:
    compose = Path("compose.yaml").read_text()
    dockerfile = Path("Dockerfile").read_text()
    dockerignore = Path(".dockerignore").read_text()

    assert "change-me-before-production" not in compose
    assert "POSTGRES_PASSWORD must be set" in compose
    assert "soulter/astrbot:v4.26.7" in dockerfile
    assert ".env" in dockerignore
    assert ".git" in dockerignore


def test_one_application_image_drives_all_runtime_roles() -> None:
    compose = Path("compose.yaml").read_text()

    assert (
        "crpi-thkewd16qu1tdfsq.cn-shenzhen.personal.cr.aliyuncs.com/stonesver/anime-qqbot"
    ) in compose
    assert "APP_IMAGE" in compose
    assert 'command: ["migrate"]' in compose
    assert 'command: ["worker"]' in compose
    assert 'command: ["astrbot"]' in compose
    assert "anime-astrbot" not in compose
    assert not Path("Dockerfile.astrbot").exists()
    assert "./astrbot_plugin_anime_tracking:" not in compose


def test_third_party_images_and_persistent_paths_are_pinned() -> None:
    compose = Path("compose.yaml").read_text()
    dockerfile = Path("Dockerfile").read_text()

    assert "soulter/astrbot:v4.26.7" in dockerfile
    assert "anime-qqbot:vendor-napcat-v4.18.13" in compose
    assert "anime-qqbot:vendor-postgres-17.4-alpine" in compose
    assert "/AstrBot/data" in compose
    assert "/app/.config/QQ" in compose
    assert "/app/napcat/config" in compose
    assert ":6185" in compose
    assert ":6099" in compose


def test_card_assets_are_shared_only_by_worker_and_astrbot() -> None:
    compose = Path("compose.yaml").read_text()

    assert "card-assets:" in compose
    assert compose.count("card-assets:/var/lib/anime-qqbot/cards") == 2
    assert "CARD_ASSET_ROOT: /var/lib/anime-qqbot/cards" in compose
    assert "CARD_CACHE_MAX_BYTES" in compose
    assert "CARD_CACHE_TARGET_BYTES" in compose
    assert "ANIME_CARD_CJK_FONT" in compose
    assert "ANIME_CARD_MONO_FONT" in compose
