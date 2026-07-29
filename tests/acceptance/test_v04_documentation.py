from __future__ import annotations

from pathlib import Path


def test_v04_versions_and_release_status_are_consistent() -> None:
    pyproject = Path("pyproject.toml").read_text()
    metadata = Path("astrbot_plugin_anime_tracking/metadata.yaml").read_text()
    readme = Path("README.md").read_text()

    assert 'version = "0.4.0"' in pyproject
    assert "version: 0.4.0" in metadata
    assert readme.startswith("# anime-qqbot v0.4.0")
    assert "自动化候选版" in readme


def test_v04_docs_explain_local_only_cards_and_external_gates() -> None:
    readme = Path("README.md").read_text()
    acceptance = Path("docs/acceptance/v0.4.0.md").read_text()

    assert "不使用占位图" in readme
    assert "群消息请求不访问" in readme
    assert "card_presentation_enabled" in readme
    assert "./scripts/deploy-acr.sh" in acceptance
    assert "--refresh-vendors" in acceptance
    assert "NapCat restart detected: no" in acceptance
    assert "external_gate" in acceptance
