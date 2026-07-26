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

    assert "astrbot:6199/ws" in compose
    assert "ONEBOT_TOKEN" in compose


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
    assert "USER animebot" in dockerfile
    assert ".env" in dockerignore
    assert ".git" in dockerignore
