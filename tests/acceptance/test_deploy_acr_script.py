"""Behavior tests for the production ACR deployment interface."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
ACR_IMAGE = "crpi-thkewd16qu1tdfsq.cn-shenzhen.personal.cr.aliyuncs.com/stonesver/anime-qqbot"


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "anime-qqbot"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    for name in ("compose.yaml", "compose.server-2g.yaml"):
        shutil.copy2(ROOT / name, project / name)
    for name in ("backup-postgres.sh", "deploy-acr.sh"):
        shutil.copy2(ROOT / "scripts" / name, scripts / name)
    (project / ".env").write_text(
        "\n".join(
            (
                f"APP_IMAGE={ACR_IMAGE}",
                "IMAGE_TAG=latest",
                "COMPOSE_FILE=compose.yaml:compose.server-2g.yaml",
                "POSTGRES_PASSWORD=real-test-password",
                "ONEBOT_TOKEN=123456789012345678901234",
                "BANGUMI_USER_AGENT=anime-qqbot/test test@example.com",
                "",
            )
        ),
        encoding="utf-8",
    )
    return project


def _make_fake_docker(tmp_path: Path) -> Path:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        """#!/usr/bin/env python3
import os
import shlex
import sys

args = sys.argv[1:]
with open(os.environ["FAKE_DOCKER_LOG"], "a", encoding="utf-8") as log:
    log.write(shlex.join(args) + "\\n")

mode = os.environ.get("FAKE_DEPLOY_MODE", "success")
running_app = os.environ.get("FAKE_RUNNING_APP", "0") == "1"
running_postgres = os.environ.get("FAKE_RUNNING_POSTGRES", "0") == "1"

if args[:2] == ["compose", "version"]:
    print("Docker Compose version v2.27.0")
elif args[:3] == ["compose", "config", "--quiet"]:
    pass
elif args[:3] == ["compose", "ps", "-q"]:
    service = args[3]
    if (service in {"worker", "astrbot"} and running_app) or (
        service == "postgres" and running_postgres
    ):
        print(f"{service}-container")
elif args and args[0] == "inspect" and any(".Image" in arg for arg in args):
    print("sha256:old-image")
elif args[:2] == ["image", "inspect"] and any(".Id" in arg for arg in args):
    print("sha256:new-image")
elif args[:2] == ["image", "inspect"] and any("RepoDigests" in arg for arg in args):
    print('["registry/anime-qqbot@sha256:digest"]')
elif args and args[0] == "pull" and mode == "pull_fail":
    sys.exit(1)
elif args[:3] == ["compose", "up", "-d"] and "postgres" in args and mode == "postgres_fail":
    sys.exit(1)
elif args[:3] == ["compose", "run", "--rm"] and mode == "migration_fail":
    sys.exit(1)
elif (
    args[:3] == ["compose", "up", "-d"]
    and "worker" in args
    and mode == "app_fail"
    and "--force-recreate" not in args
):
    sys.exit(1)
elif (
    args[:3] == ["compose", "up", "-d"]
    and "napcat" in args
    and mode == "napcat_fail"
    and "--force-recreate" not in args
):
    sys.exit(1)
elif args[:4] == ["compose", "exec", "-T", "postgres"]:
    print("-- fake postgres backup")
elif args[:2] == ["compose", "ps"]:
    print("fake compose status")
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    return fake_bin


def _run_deploy(
    tmp_path: Path,
    *,
    mode: str = "success",
    running_app: bool = False,
    running_postgres: bool = False,
    args: tuple[str, ...] = (),
    lock_held: bool = False,
    compose_file: str = "compose.yaml:compose.server-2g.yaml",
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    project = _make_project(tmp_path)
    env_file = project / ".env"
    env_file.write_text(
        env_file.read_text(encoding="utf-8").replace(
            "COMPOSE_FILE=compose.yaml:compose.server-2g.yaml",
            f"COMPOSE_FILE={compose_file}",
        ),
        encoding="utf-8",
    )
    if lock_held:
        (project / ".deploy-acr.lock").mkdir()
    fake_bin = _make_fake_docker(tmp_path)
    docker_log = tmp_path / "docker.log"
    outside = tmp_path / "outside"
    outside.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "FAKE_DOCKER_LOG": str(docker_log),
            "FAKE_DEPLOY_MODE": mode,
            "FAKE_RUNNING_APP": "1" if running_app else "0",
            "FAKE_RUNNING_POSTGRES": "1" if running_postgres else "0",
            "BACKUP_DIR": str(tmp_path / "backups"),
        }
    )
    result = subprocess.run(
        [str(project / "scripts" / "deploy-acr.sh"), *args],
        cwd=outside,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    lines = docker_log.read_text(encoding="utf-8").splitlines() if docker_log.exists() else []
    return result, lines


def _index(lines: list[str], fragment: str) -> int:
    return next(index for index, line in enumerate(lines) if fragment in line)


def test_first_deployment_pulls_and_starts_services_in_order(tmp_path: Path) -> None:
    result, lines = _run_deploy(tmp_path, args=("--no-backup",))

    assert result.returncode == 0, result.stderr
    assert _index(lines, f"pull {ACR_IMAGE}:latest") < _index(lines, "compose pull postgres napcat")
    assert _index(lines, "compose up -d --wait postgres") < _index(
        lines, "compose run --rm --no-deps migrate"
    )
    assert _index(lines, "compose run --rm --no-deps migrate") < _index(
        lines, "compose up -d --no-build --pull never --no-deps --wait worker astrbot"
    )
    assert _index(lines, "worker astrbot") < _index(
        lines, "compose up -d --no-build --pull never --no-deps --wait napcat"
    )
    assert not any("image tag sha256:old-image" in line for line in lines)
    assert not any(line.startswith("compose build") for line in lines)
    assert "no previous application image was available" in result.stdout


def test_upgrade_backs_up_and_snapshots_before_pull(tmp_path: Path) -> None:
    result, lines = _run_deploy(
        tmp_path,
        running_app=True,
        running_postgres=True,
    )

    assert result.returncode == 0, result.stderr
    backup = _index(lines, "compose exec -T postgres pg_dump")
    snapshot = _index(lines, "image tag sha256:old-image anime-qqbot:rollback")
    pull = _index(lines, f"pull {ACR_IMAGE}:latest")
    assert backup < snapshot < pull
    assert "database backup:" in result.stdout


def test_pull_failure_does_not_recreate_services(tmp_path: Path) -> None:
    result, lines = _run_deploy(
        tmp_path,
        mode="pull_fail",
        running_app=True,
        args=("--no-backup",),
    )

    assert result.returncode == 1
    assert "docker login" in result.stderr
    assert not any(line.startswith("compose up") for line in lines)


def test_migration_failure_does_not_start_applications(tmp_path: Path) -> None:
    result, lines = _run_deploy(
        tmp_path,
        mode="migration_fail",
        running_app=True,
        args=("--no-backup",),
    )

    assert result.returncode == 1
    assert "migration failed" in result.stderr
    assert not any("worker astrbot" in line and line.startswith("compose up") for line in lines)
    assert f"image tag anime-qqbot:rollback {ACR_IMAGE}:latest" in lines


def test_application_failure_restores_snapshot_and_recreates_runtime(tmp_path: Path) -> None:
    result, lines = _run_deploy(
        tmp_path,
        mode="app_fail",
        running_app=True,
        args=("--no-backup",),
    )

    assert result.returncode == 1
    assert "rollback completed" in result.stderr
    assert f"image tag anime-qqbot:rollback {ACR_IMAGE}:latest" in lines
    assert any(
        "compose up -d --no-build --pull never --no-deps --force-recreate "
        "worker astrbot napcat" in line
        for line in lines
    )


def test_napcat_failure_uses_the_same_runtime_rollback(tmp_path: Path) -> None:
    result, lines = _run_deploy(
        tmp_path,
        mode="napcat_fail",
        running_app=True,
        args=("--no-backup",),
    )

    assert result.returncode == 1
    assert "NapCat did not become healthy" in result.stderr
    assert f"image tag anime-qqbot:rollback {ACR_IMAGE}:latest" in lines
    assert any(
        "compose up -d --no-build --pull never --no-deps --force-recreate "
        "worker astrbot napcat" in line
        for line in lines
    )


def test_failed_first_deployment_reports_missing_rollback(tmp_path: Path) -> None:
    result, _ = _run_deploy(
        tmp_path,
        mode="app_fail",
        args=("--no-backup",),
    )

    assert result.returncode == 2
    assert "no previous application image is available for rollback" in result.stderr


def test_concurrent_deployment_is_rejected_before_docker_changes(tmp_path: Path) -> None:
    result, lines = _run_deploy(tmp_path, lock_held=True)

    assert result.returncode == 1
    assert "another deployment is already running" in result.stderr
    assert lines == []


def test_server_resource_overlay_is_required_before_docker_changes(tmp_path: Path) -> None:
    result, lines = _run_deploy(tmp_path, compose_file="compose.yaml")

    assert result.returncode == 1
    assert "COMPOSE_FILE must be compose.yaml:compose.server-2g.yaml" in result.stderr
    assert lines == []
