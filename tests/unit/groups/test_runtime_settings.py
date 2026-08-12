from __future__ import annotations

from uuid import uuid4

from anime_qqbot.groups.settings import GroupRuntimePolicy


def test_general_chat_is_disabled_by_default() -> None:
    policy = GroupRuntimePolicy(
        chat_group_id=uuid4(),
        timezone="Asia/Shanghai",
        group_enabled=True,
    )

    assert policy.general_chat_enabled is False
