"""Acceptance tests for the server deployment bundle."""

from __future__ import annotations

import subprocess
import tarfile
from pathlib import Path


def test_deployment_package_contains_only_the_runtime_whitelist(tmp_path: Path) -> None:
    output = tmp_path / "anime-qqbot-deployment.tar.gz"
    result = subprocess.run(
        ["scripts/package-deployment.sh", str(output)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert output.is_file()
    with tarfile.open(output, "r:gz") as archive:
        members = {
            member.name.rstrip("/") for member in archive.getmembers() if member.name.rstrip("/")
        }
    assert members == {
        "anime-qqbot",
        "anime-qqbot/.env.example",
        "anime-qqbot/compose.yaml",
        "anime-qqbot/compose.server-2g.yaml",
        "anime-qqbot/scripts",
        "anime-qqbot/scripts/backup-postgres.sh",
        "anime-qqbot/scripts/deploy-acr.sh",
        "anime-qqbot/scripts/napcat-entrypoint.sh",
        "anime-qqbot/scripts/restore-postgres.sh",
    }
    assert "SHA-256" in result.stdout
