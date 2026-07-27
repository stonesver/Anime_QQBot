"""Acceptance tests for v0.2 fixed commands and compose (Tasks 26-31)."""

from __future__ import annotations

from pathlib import Path


def test_all_fixed_commands_in_parser() -> None:
    from anime_qqbot.application import parse_fixed_command, Intent

    commands = [
        "/番剧 今天",
        "/番剧 本周",
        "/番剧 季度 夏",
        "/番剧 搜索 test",
        "/番剧 详情 aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeee1",
        "/番剧 下次 aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeee1",
        "/番剧 订阅 aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeee1",
        "/番剧 取消订阅 aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeee1",
        "/番剧 我的订阅",
        "/番剧 订阅设置 aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeee1",
        "/番剧 状态",
        "/番剧 映射待处理",
        "/番剧 帮助",
    ]
    for cmd in commands:
        result = parse_fixed_command(cmd)
        assert isinstance(result, Intent), f"Failed to parse: {cmd}"


def test_compose_has_five_services() -> None:
    compose = Path("compose.yaml").read_text()

    for svc in ("postgres:", "migrate:", "worker:", "napcat:", "astrbot:"):
        assert svc in compose, f"{svc} missing from compose.yaml"


def test_migrations_are_present() -> None:
    versions = sorted(Path("migrations/versions").glob("*.py"))
    assert len(versions) >= 6  # 0001-0010
    assert any("0005_multisource" in v.name for v in versions)
    assert any("0008_following" in v.name for v in versions)
    assert any("0009_resource" in v.name for v in versions)


def test_dockerfiles_exist() -> None:
    assert Path("Dockerfile").exists()
    assert Path("Dockerfile.astrbot").exists()