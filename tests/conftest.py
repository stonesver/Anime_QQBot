"""Pytest configuration shared by every test layer."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_PATH = ROOT / "astrbot_plugin_anime_tracking"
if str(PLUGIN_PATH) not in sys.path:
    sys.path.insert(0, str(PLUGIN_PATH))
SRC_PATH = ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

# Make sure the unit-test layer cannot accidentally inherit a
# DATABASE_URL from the developer's shell. Integration tests
# always set ``TEST_DATABASE_URL`` explicitly; the unit layer
# only relies on default values.
os.environ.pop("DATABASE_URL", None)

from anime_qqbot.clock import FrozenClock  # noqa: E402


@pytest.fixture
def frozen_clock() -> FrozenClock:
    return FrozenClock(datetime(2026, 7, 15, 8, 0, tzinfo=UTC))
