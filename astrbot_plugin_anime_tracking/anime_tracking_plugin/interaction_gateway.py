"""Single deterministic entry point for non-command group messages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID
from zoneinfo import ZoneInfo

from anime_qqbot.application.context import ChatContext
from anime_qqbot.application.intents import Intent
from anime_qqbot.application.parser import ParseFailure, parse_fixed_command
from anime_qqbot.groups.repository_v2 import ChatGroupRepository, GroupEvent
from anime_qqbot.groups.settings import (
    GroupRuntimePolicy,
    GroupRuntimeSettingsRepository,
)
from anime_qqbot.interactions.parser import (
    parse_direct_shortcut,
    parse_mention_command,
    parse_reply_number,
)
from anime_qqbot.notifications.governor import (
    DeliveryClass,
    SendRequest,
)
from anime_qqbot.operations.repository import AdminAuditRepository

from .adapter import EventAdapter
from .event_envelope import EventEnvelope
from .lifecycle import PluginLifecycle
from .rendering import render_reply


@dataclass(frozen=True)
class GatewayResult:
    matched: bool
    text: str | None = None
    stop_propagation: bool = False

    @classmethod
    def ignored(cls) -> GatewayResult:
        return cls(matched=False)


class InteractionGateway:
    def __init__(self, lifecycle: PluginLifecycle) -> None:
        self._lifecycle = lifecycle

    async def route(self, envelope: EventEnvelope) -> GatewayResult:
        if not bool(self._lifecycle.config.get("interaction_gateway_enabled", False)):
            return GatewayResult.ignored()
        sessions = self._lifecycle.sessions
        if sessions is None or not envelope.group_id or not envelope.user_id:
            return GatewayResult.ignored()
        now = datetime.now(UTC)
        group = await ChatGroupRepository(sessions).upsert_group_event(
            GroupEvent(
                platform=envelope.platform,
                external_group_id=envelope.group_id,
                external_user_id=envelope.user_id,
                display_name=envelope.display_name or envelope.user_id,
                unified_msg_origin=envelope.unified_msg_origin,
                timestamp=now,
            )
        )
        policy_repo = GroupRuntimeSettingsRepository(sessions)
        policy = await policy_repo.get_policy(group.id)
        if not policy.passive_enabled:
            return GatewayResult.ignored()

        owner_result = await self._owner_command(envelope, group.id, policy_repo, policy, now)
        if owner_result is not None:
            return owner_result

        intent, matched = self._parse(envelope, policy)
        if not matched:
            return GatewayResult.ignored()
        if isinstance(intent, ParseFailure):
            return GatewayResult(
                matched=True,
                text=f"没听懂这个操作：{intent.reason}",
                stop_propagation=True,
            )
        if bool(self._lifecycle.config.get("send_governor_enabled", False)):
            permit = self._lifecycle.governor.acquire(
                SendRequest(
                    DeliveryClass.INTERACTIVE,
                    envelope.group_id,
                    envelope.user_id,
                )
            )
            if not permit.allowed:
                seconds = max(1, round(permit.retry_after_seconds))
                return GatewayResult(
                    matched=True,
                    text=f"请求有点快，请 {seconds} 秒后再试。",
                    stop_propagation=True,
                )

        ctx = ChatContext(
            platform=envelope.platform,
            group_id=envelope.group_id,
            user_id=envelope.user_id,
            display_name=envelope.display_name,
            unified_msg_origin=envelope.unified_msg_origin,
            timezone=ZoneInfo(policy.timezone),
            is_admin=envelope.is_owner,
        )
        adapter = EventAdapter(sessions=sessions)
        reply = await adapter.handle_intent(ctx=ctx, intent=intent, now=now)
        if reply.candidate_items:
            await adapter.persist_candidates(ctx=ctx, reply=reply, now=now)
        return GatewayResult(
            matched=True,
            text=await render_reply(reply, envelope),
            stop_propagation=True,
        )

    @staticmethod
    def _parse(
        envelope: EventEnvelope, policy: GroupRuntimePolicy
    ) -> tuple[Intent | ParseFailure, bool]:
        if envelope.text.startswith("/番剧"):
            return parse_fixed_command(envelope.text), True
        if envelope.mentions_bot and getattr(policy, "mention_enabled", False):
            return parse_mention_command(_strip_textual_mention(envelope.text)), True
        if envelope.reply_to_message_id:
            parsed_number = parse_reply_number(envelope.text)
            if not isinstance(parsed_number, ParseFailure):
                # The adapter still validates scope and TTL. A plain-number
                # flow is ignored unless the reply component is present.
                return parsed_number, True
        if getattr(policy, "direct_shortcuts_enabled", False):
            parsed = parse_direct_shortcut(envelope.text)
            return parsed, not isinstance(parsed, ParseFailure)
        return ParseFailure("no interaction entry matched"), False

    async def _owner_command(
        self,
        envelope: EventEnvelope,
        group_id: UUID,
        policy_repo: GroupRuntimeSettingsRepository,
        policy: GroupRuntimePolicy,
        now: datetime,
    ) -> GatewayResult | None:
        if not envelope.mentions_bot:
            return None
        text = _strip_textual_mention(envelope.text)
        if text == "本群设置":
            return GatewayResult(
                True,
                (
                    "本群设置\n"
                    f"@入口：{'开' if policy.mention_enabled else '关'}\n"
                    f"短命令：{'开' if policy.direct_shortcuts_enabled else '关'}\n"
                    f"主动提醒：{'开' if policy.active_notifications_enabled else '关'}"
                ),
                True,
            )
        mapping = {
            "开启短命令": ("direct_shortcuts_enabled", True),
            "关闭短命令": ("direct_shortcuts_enabled", False),
            "开启提醒": ("active_notifications_enabled", True),
            "关闭提醒": ("active_notifications_enabled", False),
            "开启@入口": ("mention_enabled", True),
            "关闭@入口": ("mention_enabled", False),
        }
        change = mapping.get(text)
        if change is None:
            return None
        if not envelope.is_owner:
            return GatewayResult(True, "仅机器人所有者可修改本群设置。", True)
        if not bool(self._lifecycle.config.get("admin_page_writes_enabled", False)):
            return GatewayResult(True, "管理写操作尚未启用。", True)
        field, value = change
        before: dict[str, object] = {
            "mention_enabled": policy.mention_enabled,
            "direct_shortcuts_enabled": policy.direct_shortcuts_enabled,
            "active_notifications_enabled": policy.active_notifications_enabled,
        }
        changed = await policy_repo.update_policy(
            group_id,
            expected_version=policy.version,
            now=now,
            **{field: value},
        )
        after: dict[str, object] = {
            "mention_enabled": changed.mention_enabled,
            "direct_shortcuts_enabled": changed.direct_shortcuts_enabled,
            "active_notifications_enabled": changed.active_notifications_enabled,
        }
        actor = sha256(envelope.user_id.encode()).hexdigest()[:16]
        sessions = self._lifecycle.sessions
        assert sessions is not None
        await AdminAuditRepository(sessions).append(
            actor=actor,
            action="group.policy.update",
            target_type="group",
            target_id=envelope.group_id,
            before_summary=before,
            after_summary=after,
            result="success",
            error_summary=None,
            now=now,
        )
        return GatewayResult(True, "本群设置已更新。", True)


def _strip_textual_mention(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("@"):
        parts = stripped.split(maxsplit=1)
        return parts[1] if len(parts) == 2 else ""
    return stripped


__all__ = ["GatewayResult", "InteractionGateway"]
