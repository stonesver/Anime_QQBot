"""Acceptance tests for the public combined-image entrypoint."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ENTRYPOINT = Path("scripts/container-entrypoint.sh").resolve()


def _fake_python(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    capture = tmp_path / "python-args"
    executable = bin_dir / "python"
    executable.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" > "$ENTRYPOINT_CAPTURE"\npwd > "$ENTRYPOINT_CAPTURE.cwd"\n',
    )
    executable.chmod(0o755)
    return bin_dir, capture


def _run_entrypoint(
    tmp_path: Path,
    *args: str,
    plugin_source: Path | None = None,
    data_dir: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    bin_dir, capture = _fake_python(tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "ENTRYPOINT_CAPTURE": str(capture),
            "ANIME_PLUGIN_SOURCE": str(plugin_source or tmp_path / "missing-plugin"),
            "ASTRBOT_DATA_DIR": str(data_dir or tmp_path / "astrbot-data"),
            "ASTRBOT_MAIN": str(tmp_path / "AstrBot" / "main.py"),
            "ANIME_APP_DIR": str(tmp_path / "app"),
        }
    )
    (tmp_path / "app").mkdir(exist_ok=True)
    result = subprocess.run(
        [str(ENTRYPOINT), *args],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, capture


def test_astrbot_role_replaces_persisted_plugin_with_image_copy(tmp_path: Path) -> None:
    source = tmp_path / "image-plugin"
    source.mkdir()
    (source / "new-version.txt").write_text("0.2.0")
    data_dir = tmp_path / "astrbot-data"
    persisted = data_dir / "plugins" / "astrbot_plugin_anime_tracking"
    persisted.mkdir(parents=True)
    (persisted / "stale-file.txt").write_text("old")

    result, capture = _run_entrypoint(
        tmp_path,
        "astrbot",
        plugin_source=source,
        data_dir=data_dir,
    )

    assert result.returncode == 0, result.stderr
    assert (persisted / "new-version.txt").read_text() == "0.2.0"
    assert not (persisted / "stale-file.txt").exists()
    assert capture.read_text().strip() == str(tmp_path / "AstrBot" / "main.py")


def test_default_role_starts_astrbot(tmp_path: Path) -> None:
    source = tmp_path / "image-plugin"
    source.mkdir()

    result, capture = _run_entrypoint(tmp_path, plugin_source=source)

    assert result.returncode == 0, result.stderr
    assert capture.read_text().strip() == str(tmp_path / "AstrBot" / "main.py")


def test_anime_core_roles_dispatch_to_cli(tmp_path: Path) -> None:
    for role, extra in (
        ("worker", ()),
        ("migrate", ()),
        ("map-mikan", ("--anime-id", "00000000-0000-0000-0000-000000000001")),
        ("map-anilist", ("--anilist-id", "1")),
    ):
        role_tmp = tmp_path / role
        role_tmp.mkdir()
        result, capture = _run_entrypoint(role_tmp, role, *extra)

        assert result.returncode == 0, result.stderr
        expected = " ".join(("-m", "anime_qqbot.entrypoints.cli", role, *extra))
        assert capture.read_text().strip() == expected
        assert Path(f"{capture}.cwd").read_text().strip() == str(role_tmp / "app")


def test_unknown_role_is_rejected(tmp_path: Path) -> None:
    result, _ = _run_entrypoint(tmp_path, "unknown-role")

    assert result.returncode == 64
    assert "unknown role: unknown-role" in result.stderr
