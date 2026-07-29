from __future__ import annotations

from pathlib import Path


def test_runtime_image_installs_fonts_and_runs_real_card_smoke() -> None:
    dockerfile = Path("Dockerfile").read_text()

    assert "fonts-noto-cjk" in dockerfile
    assert "fonts-dejavu-core" in dockerfile
    assert "python -m anime_qqbot.entrypoints.card_smoke" in dockerfile
    assert "soulter/astrbot:v4.26.7" in dockerfile


def test_local_card_artifacts_are_excluded_from_image_context() -> None:
    dockerignore = Path(".dockerignore").read_text()

    assert "card-assets" in dockerignore
    assert "card-benchmark*.json" in dockerignore
    assert "card-smoke*.png" in dockerignore
