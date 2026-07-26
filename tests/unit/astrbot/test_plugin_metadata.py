"""Tests for plugin metadata and lifecycle (Task 8)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# The plugin directory lives at the repo root, outside src/.
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

PLUGIN_DIR = Path(__file__).parents[3] / "astrbot_plugin_anime_tracking"


def _metadata_text() -> str:
    return (PLUGIN_DIR / "metadata.yaml").read_text()


def test_metadata_has_required_fields() -> None:
    text = _metadata_text()

    assert "name: anime_tracking" in text
    assert "version:" in text
    assert "support_platforms:" in text
    assert "aiocqhttp" in text


def test_conf_schema_exposes_only_non_secret_keys() -> None:
    schema = json.loads((PLUGIN_DIR / "_conf_schema.json").read_text())
    props = schema.get("properties", {})

    assert isinstance(props, dict)
    assert "password" not in props
    assert "secret" not in props


def test_plugin_directory_compiles_without_syntax_errors() -> None:
    import compileall

    success = compileall.compile_dir(  # type: ignore[func-returns-value]
        str(PLUGIN_DIR), quiet=1, force=True
    )
    assert success != 0  # non-zero means success for compile_dir


def test_requirements_file_is_parseable() -> None:
    lines = (PLUGIN_DIR / "requirements.txt").read_text().strip().splitlines()
    deps = [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]

    assert any("astrbot" in dep for dep in deps)


def test_fake_context_can_hold_lifecycle() -> None:
    from tests.unit.astrbot.fakes import FakeContext

    from astrbot_plugin_anime_tracking.anime_tracking_plugin.lifecycle import (
        PluginLifecycle,
    )

    ctx = FakeContext()
    lc = PluginLifecycle.from_context(ctx)

    assert lc._context is ctx
    assert PluginLifecycle.from_context(ctx) is lc


@pytest.mark.asyncio
async def test_lifecycle_start_stop_is_idempotent() -> None:
    from astrbot_plugin_anime_tracking.anime_tracking_plugin.lifecycle import (
        PluginLifecycle,
    )

    lc = PluginLifecycle()
    await lc.start()
    assert lc.running is True
    await lc.start()
    assert lc.running is True
    await lc.shutdown()
    assert lc.running is False
    await lc.shutdown()
    assert lc.running is False