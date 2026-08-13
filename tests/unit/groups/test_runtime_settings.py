from __future__ import annotations

from uuid import uuid4

from anime_qqbot.groups.settings import GroupRuntimePolicy, LLMMode


def test_group_llm_defaults_to_anime_only_with_image_replies() -> None:
    policy = GroupRuntimePolicy(
        chat_group_id=uuid4(),
        timezone="Asia/Shanghai",
        group_enabled=True,
    )

    assert policy.llm_mode is LLMMode.ANIME_ONLY
    assert policy.llm_enabled is True
    assert policy.general_chat_enabled is False
    assert policy.llm_image_reply_enabled is True
