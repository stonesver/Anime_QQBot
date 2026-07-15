from datetime import UTC, datetime

import pytest

from anime_qqbot.clock import FrozenClock


@pytest.fixture
def frozen_clock() -> FrozenClock:
    return FrozenClock(datetime(2026, 7, 15, 8, 0, tzinfo=UTC))
