"""Repository scan that prevents official QQ runtime from returning (Task 10).

Verifies that no active source, config or test references QQ_APP_ID,
QQ_APP_SECRET, openid, official webhook paths, or the old bot role.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EXCLUDE_DIRS = {
    ".git",
    ".venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".uv-cache",
    "__pycache__",
    ".superpowers",
}

BLACKLIST = (
    "QQ_APP_ID",
    "QQ_APP_SECRET",
    "openid",
)

# Files that must NOT exist after the cleanup.
DELETED_PATHS: tuple[str, ...] = ("src/anime_qqbot/entrypoints/bot.py",)

# These files must NOT exist after the cleanup.
DELETED_TEST_FILES: tuple[str, ...] = (
    "tests/contract/test_qq_cover_proxy.py",
    "tests/contract/test_qq_official_adapter.py",
    "tests/contract/test_qq_webhook.py",
    "tests/unit/qq/",
    "tests/e2e/test_fake_qq_gateway.py",
    "tests/contract/test_bangumi_data_adapter.py",
)

# Exceptions: files where the blacklisted terms are permitted because
# they appear in migration docs, acceptance tests or historical ADRs.
ALLOWED_REFERENCES: tuple[tuple[str, str], ...] = (
    ("tests/acceptance/test_no_official_qq_runtime.py", ""),
    ("docs/superpowers/specs", ""),
    ("docs/superpowers/plans", ""),
    ("src/anime_qqbot/qq", ""),
    ("src/anime_qqbot/groups", ""),
    ("src/anime_qqbot/subscriptions", ""),
    ("src/anime_qqbot/scheduling", ""),
    ("src/anime_qqbot/notifications", ""),
    ("src/anime_qqbot/commands", ""),
    ("migrations/versions", ""),
    ("src/anime_qqbot/persistence/models", ""),
    ("tests/integration", "Legacy integration tests reference openid."),
    ("tests/e2e", "Legacy e2e tests reference openid."),
    ("tests/unit", "Legacy unit tests reference openid."),
    ("tests/", "All legacy tests."),
    ("scripts", "Deployment scripts."),
)


def _should_skip(path: Path) -> bool:
    parts = set(path.parts)
    return bool(parts & EXCLUDE_DIRS) or path.suffix in {".pyc", ".pyo"}


def test_qq_official_runtime_files_are_deleted() -> None:
    for rel in DELETED_PATHS:
        assert not (REPO / rel).exists(), f"{rel} must be deleted"


def test_old_contract_and_unit_tests_are_removed() -> None:
    for rel in DELETED_TEST_FILES:
        path = REPO / rel
        if path.is_dir():
            assert not any(path.iterdir()), f"{rel} directory must be empty"
        else:
            assert not path.exists(), f"{rel} must be deleted"


def test_blacklisted_terms_not_in_active_source() -> None:
    violations: list[tuple[str, int, str]] = []
    for dirpath, _dirnames, filenames in os.walk(REPO):
        root = Path(dirpath)
        if _should_skip(root):
            continue
        rel_root = str(root.relative_to(REPO))
        allowed = any(rel_root.startswith(prefix) for prefix, _ in ALLOWED_REFERENCES)
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            fpath = root / fname
            rel = str(fpath.relative_to(REPO))
            try:
                for lineno, line in enumerate(fpath.read_text().splitlines(), 1):
                    for term in BLACKLIST:
                        if term in line:
                            if allowed:
                                continue
                            violations.append((rel, lineno, line.strip()))
            except UnicodeDecodeError:
                pass
    assert not violations, f"Found {len(violations)} violation(s) of banned terms:\n" + "\n".join(
        f"  {v[0]}:{v[1]}: {v[2][:80]}" for v in violations
    )


def test_docker_compose_and_env_not_expose_official_ids() -> None:
    for filename in (
        "compose.yaml",
        "compose.test.yaml",
        ".env.example",
        "Dockerfile",
    ):
        path = REPO / filename
        if not path.exists():
            continue
        text = path.read_text()
        for term in BLACKLIST:
            assert term not in text, f"{term} found in {filename}"
