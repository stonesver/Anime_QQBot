import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
ACR_IMAGE = "crpi-thkewd16qu1tdfsq.cn-shenzhen.personal.cr.aliyuncs.com/stonesver/anime-qqbot"


def make_project(tmp_path: Path) -> Path:
    project = tmp_path / "anime-qqbot"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(ROOT / "compose.yaml", project / "compose.yaml")
    shutil.copy2(ROOT / "scripts" / "backup-postgres.sh", scripts / "backup-postgres.sh")
    shutil.copy2(ROOT / "scripts" / "deploy-acr.sh", scripts / "deploy-acr.sh")
    (project / ".env").write_text("IMAGE_TAG=latest\n", encoding="utf-8")
    return project


def make_fake_docker(tmp_path: Path) -> Path:
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

state_file = os.environ["FAKE_DOCKER_STATE"]
if args[:2] == ["compose", "up"] and "migrate" in args:
    open(state_file, "w", encoding="utf-8").write("new")
elif args[:4] == ["image", "tag", "anime-qqbot:rollback", "anime-qqbot:latest"]:
    open(state_file, "w", encoding="utf-8").write("rollback")

if args[:2] == ["compose", "version"]:
    print("Docker Compose version v2.27.0")
elif args[:3] == ["compose", "config", "--images"]:
    print(os.environ.get("FAKE_COMPOSE_IMAGE", "anime-qqbot:latest"))
    print("postgres:17.4-alpine")
elif args[:3] == ["compose", "ps", "-q"]:
    print(f"{args[3]}-container")
elif args[:4] == ["compose", "ps", "-a", "-q"]:
    print(f"{args[4]}-container")
elif args and args[0] == "inspect" and any(".Image" in arg for arg in args):
    print("sha256:old-image")
elif args and args[0] == "inspect" and any(".State.ExitCode" in arg for arg in args):
    print("0")
elif args and args[0] == "inspect" and any(".State.Health" in arg for arg in args):
    state = open(state_file, encoding="utf-8").read() if os.path.exists(state_file) else "old"
    mode = os.environ.get("FAKE_DEPLOY_MODE")
    if mode in {"fail_new", "rollback_fail"} and state == "new":
        print("unhealthy")
    elif mode == "rollback_fail" and state == "rollback":
        print("unhealthy")
    else:
        print("healthy")
elif args[:4] == ["compose", "exec", "-T", "postgres"]:
    print("-- fake postgres backup")
elif args and args[0] == "pull" and os.environ.get("FAKE_DEPLOY_MODE") == "pull_fail":
    sys.exit(1)
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    return fake_bin


def run_deploy(
    tmp_path: Path,
    *,
    mode: str = "success",
    extra_env: dict[str, str] | None = None,
    lock_held: bool = False,
) -> tuple[subprocess.CompletedProcess[str], str]:
    project = make_project(tmp_path)
    if lock_held:
        (project / ".deploy-acr.lock").mkdir()
    fake_bin = make_fake_docker(tmp_path)
    log = tmp_path / "docker.log"
    backup_dir = tmp_path / "backups"
    outside = tmp_path / "outside"
    outside.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "FAKE_DOCKER_LOG": str(log),
            "FAKE_DOCKER_STATE": str(tmp_path / "docker.state"),
            "FAKE_DEPLOY_MODE": mode,
            "BACKUP_DIR": str(backup_dir),
            "DEPLOY_TIMEOUT_SECONDS": "2",
        }
    )
    env.update(extra_env or {})
    result = subprocess.run(
        [str(project / "scripts" / "deploy-acr.sh")],
        cwd=outside,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    docker_log = log.read_text(encoding="utf-8") if log.exists() else ""
    return result, docker_log


def test_deploys_latest_acr_image_from_any_working_directory(tmp_path: Path) -> None:
    result, docker_log = run_deploy(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "deployment completed" in result.stdout
    assert "image tag sha256:old-image anime-qqbot:rollback" in docker_log
    assert f"pull {ACR_IMAGE}:latest" in docker_log
    assert f"image tag {ACR_IMAGE}:latest anime-qqbot:latest" in docker_log
    assert "compose up -d --no-build --force-recreate migrate bot worker" in docker_log


def test_unhealthy_new_version_rolls_back_running_services(tmp_path: Path) -> None:
    result, docker_log = run_deploy(tmp_path, mode="fail_new")

    assert result.returncode != 0
    assert "new version deployment failed" in result.stderr
    assert "rollback completed" in result.stderr
    assert "image tag anime-qqbot:rollback anime-qqbot:latest" in docker_log
    assert "compose up -d --no-build --no-deps --force-recreate bot worker" in docker_log


def test_backup_can_be_explicitly_skipped(tmp_path: Path) -> None:
    result, docker_log = run_deploy(tmp_path, extra_env={"SKIP_BACKUP": "1"})

    assert result.returncode == 0, result.stderr
    assert "compose exec -T postgres pg_dump" not in docker_log
    assert "database backup: skipped" in result.stdout


def test_pull_failure_does_not_replace_running_services(tmp_path: Path) -> None:
    result, docker_log = run_deploy(tmp_path, mode="pull_fail")

    assert result.returncode != 0
    assert "docker login" in result.stderr
    assert f"image tag {ACR_IMAGE}:latest anime-qqbot:latest" not in docker_log
    assert "compose up" not in docker_log


def test_wrong_compose_image_tag_stops_before_pull(tmp_path: Path) -> None:
    result, docker_log = run_deploy(
        tmp_path, extra_env={"FAKE_COMPOSE_IMAGE": "anime-qqbot:acr-latest"}
    )

    assert result.returncode != 0
    assert "set IMAGE_TAG=latest in .env" in result.stderr
    assert f"pull {ACR_IMAGE}:latest" not in docker_log


def test_invalid_deploy_timeout_is_rejected(tmp_path: Path) -> None:
    result, docker_log = run_deploy(tmp_path, extra_env={"DEPLOY_TIMEOUT_SECONDS": "soon"})

    assert result.returncode != 0
    assert "DEPLOY_TIMEOUT_SECONDS must be a positive integer" in result.stderr
    assert docker_log == ""


def test_failed_rollback_returns_distinct_exit_code(tmp_path: Path) -> None:
    result, _ = run_deploy(tmp_path, mode="rollback_fail")

    assert result.returncode == 2
    assert "rollback services did not become healthy" in result.stderr


def test_concurrent_deployment_is_rejected_before_docker_changes(tmp_path: Path) -> None:
    result, docker_log = run_deploy(tmp_path, lock_held=True)

    assert result.returncode != 0
    assert "another deployment is already running" in result.stderr
    assert docker_log == ""
