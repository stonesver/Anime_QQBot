"""Acceptance tests for v0.2 documentation completeness (Task 30)."""

from __future__ import annotations

from pathlib import Path


def test_readme_describes_astrbot_architecture() -> None:
    readme = Path("README.md").read_text()

    assert "AstrBot" in readme
    assert "NapCat" in readme
    assert "docker compose" in readme.lower()
    # v0.2 non-goal mentions QQ official bot for migration context — fine.
    assert """## 架构""" in readme


def test_deployment_doc_exists() -> None:
    assert Path("docs/deployment.md").exists()


def test_operations_doc_exists() -> None:
    assert Path("docs/operations.md").exists()


def test_acceptance_report_exists() -> None:
    assert Path("docs/acceptance/v0.2.0.md").exists()


def test_no_official_qq_paths_in_docs() -> None:
    for path in Path("docs").rglob("*.md"):
        text = path.read_text()
        # Historical acceptance reports and design docs may reference old
        # QQ runtime; skip them.
        if any(marker in str(path) for marker in (
            "v0.1", "2026-07-15", "2026-07-16", "2026-07-17",
        )):
            continue
        if "已移除" in text or "历史" in text or "superseded" in text.lower():
            continue
        assert "QQ_APP_ID" not in text, f"QQ_APP_ID found in {path}"
        assert "QQ_APP_SECRET" not in text, f"QQ_APP_SECRET found in {path}"
