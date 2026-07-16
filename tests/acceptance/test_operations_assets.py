import os
from pathlib import Path


def test_operations_scripts_are_executable_and_restore_requires_confirmation() -> None:
    backup = Path("scripts/backup-postgres.sh")
    restore = Path("scripts/restore-postgres.sh")
    assert os.access(backup, os.X_OK)
    assert os.access(restore, os.X_OK)
    assert "pg_dump" in backup.read_text()
    assert "gzip -t" in backup.read_text()
    restore_text = restore.read_text()
    assert 'answer" = "restore anime"' in restore_text
    assert "DROP SCHEMA public CASCADE" in restore_text
    assert "docker compose run --rm migrate" in restore_text
    assert "RESTORE_SKIP_APP_START" in restore_text


def test_documented_links_exist_and_secret_files_are_ignored() -> None:
    root = Path.cwd()
    readme = (root / "README.md").read_text()
    assert "docs/deployment.md" in readme
    assert "docs/operations.md" in readme
    assert (root / "docs/deployment.md").is_file()
    assert (root / "docs/operations.md").is_file()
    assert ".env" in (root / ".gitignore").read_text().splitlines()
    assert ".env" in (root / ".dockerignore").read_text().splitlines()
