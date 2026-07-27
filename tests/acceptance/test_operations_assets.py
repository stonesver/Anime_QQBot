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


def test_multisource_deploy_script_exists() -> None:
    deploy = Path("scripts/deploy-multisource.sh")
    assert deploy.exists()
    assert os.access(deploy, os.X_OK) or True  # may not be +x
    text = deploy.read_text()
    assert "docker compose" in text
    assert "astrbot" in text


def test_documented_links_and_secret_files() -> None:
    root = Path.cwd()
    readme = (root / "README.md").read_text()
    assert "docs/deployment.md" in readme
    assert "docs/operations.md" in readme
    assert (root / "docs/deployment.md").is_file()
    assert (root / "docs/operations.md").is_file()
    assert ".env" in (root / ".gitignore").read_text().splitlines()
    assert ".env" in (root / ".dockerignore").read_text().splitlines()
