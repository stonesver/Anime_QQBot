from datetime import UTC, datetime

import pytest

from anime_qqbot.qq.contracts import QQEvent, QQEventType


def test_group_event_requires_group_scoped_identity() -> None:
    with pytest.raises(ValueError, match="group_openid"):
        QQEvent("event", QQEventType.GROUP_AT_MESSAGE, datetime.now(UTC))


def test_private_event_requires_user_openid() -> None:
    with pytest.raises(ValueError, match="user_openid"):
        QQEvent("event", QQEventType.C2C_MESSAGE, datetime.now(UTC))
