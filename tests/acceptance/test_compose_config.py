from pathlib import Path


def test_compose_declares_migration_gate_healthchecks_and_persistent_database() -> None:
    compose = Path("compose.yaml").read_text()
    assert "condition: service_completed_successfully" in compose
    assert compose.count("healthcheck:") >= 3
    assert "postgres-data:/var/lib/postgresql/data" in compose
    assert 'restart: "no"' in compose


def test_runtime_image_is_non_root_and_excludes_secrets() -> None:
    compose = Path("compose.yaml").read_text()
    dockerfile = Path("Dockerfile").read_text()
    dockerignore = Path(".dockerignore").read_text().splitlines()
    assert "change-me-before-production" not in compose
    assert "POSTGRES_PASSWORD must be set" in compose
    assert "127.0.0.1:${QQ_WEBHOOK_PORT:-8080}:8080" in compose
    assert "USER animebot" in dockerfile
    assert ".env" in dockerignore
    assert ".git" in dockerignore
