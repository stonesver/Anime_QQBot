"""Acceptance tests for v0.2 operations assets."""

from __future__ import annotations

import os
from pathlib import Path


def test_operations_scripts_are_executable() -> None:
    backup = Path("scripts/backup-postgres.sh")
    restore = Path("scripts/restore-postgres.sh")
    assert os.access(backup, os.X_OK)
    assert os.access(restore, os.X_OK)
    assert "pg_dump" in backup.read_text()
    assert "gzip -t" in backup.read_text()
    restore_text = restore.read_text()
    assert 'answer" = "restore anime"' in restore_text
    assert "DROP SCHEMA public CASCADE" in restore_text


def test_acr_deploy_script_is_the_only_active_deploy_interface() -> None:
    deploy = Path("scripts/deploy-acr.sh")
    assert deploy.exists()
    assert os.access(deploy, os.X_OK)
    text = deploy.read_text()
    assert "docker compose" in text
    assert "astrbot" in text
    assert "ONEBOT_TOKEN" in text
    assert "docker compose run --rm --no-deps migrate" in text
    assert "docker build" not in text
    assert not Path("scripts/deploy-multisource.sh").exists()


def test_restore_targets_only_v02_runtime_services() -> None:
    text = Path("scripts/restore-postgres.sh").read_text()

    assert "stop worker astrbot napcat" in text
    assert "0011_complete_mikan_pipeline (head)" in text
    assert " bot " not in text


def test_documented_links_and_secret_files() -> None:
    root = Path.cwd()
    readme = (root / "README.md").read_text()
    assert "docs/deployment.md" in readme
    assert "docs/operations.md" in readme
    assert (root / "docs/deployment.md").is_file()
    assert (root / "docs/operations.md").is_file()
    assert ".env" in (root / ".gitignore").read_text().splitlines()
    assert ".env" in (root / ".dockerignore").read_text().splitlines()
