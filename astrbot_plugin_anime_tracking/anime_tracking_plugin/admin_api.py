"""Authenticated AstrBot Plugin Page API adapter."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from hashlib import sha256
from typing import Any

from anime_qqbot.application.admin_service import (
    AdminNotFoundError,
    AdminService,
    AdminValidationError,
)
from anime_qqbot.groups.settings import PolicyVersionConflictError

try:
    from astrbot.api.web import (  # type: ignore[import-not-found]
        error_response,
        json_response,
        request,
    )
except ModuleNotFoundError:
    request = None

    def json_response(value: object) -> object:
        return value

    def error_response(message: str, status_code: int = 400) -> object:
        return {"status": "error", "message": message, "status_code": status_code}


PLUGIN_NAME = "anime_tracking"


class AdminWebAPI:
    def __init__(
        self,
        context: Any,
        lifecycle_provider: Callable[[], Awaitable[Any]],
    ) -> None:
        self._lifecycle_provider = lifecycle_provider
        register = getattr(context, "register_web_api", None)
        if not callable(register):
            return
        routes = (
            ("overview", self.overview, ["GET"]),
            ("groups", self.groups, ["GET"]),
            ("subscriptions", self.subscriptions, ["GET"]),
            ("mappings", self.mappings, ["GET"]),
            ("notifications", self.notifications, ["GET"]),
            ("sources", self.sources, ["GET"]),
            ("jobs", self.jobs, ["GET"]),
            ("controls", self.controls, ["GET"]),
            ("groups/<group_id>/update", self.update_group, ["POST"]),
            ("delivery/global", self.global_delivery, ["POST"]),
            ("jobs/enqueue", self.enqueue_job, ["POST"]),
            (
                "subscriptions/<subscription_id>/cancel",
                self.cancel_subscription,
                ["POST"],
            ),
            ("mappings/<mapping_id>/review", self.review_mapping, ["POST"]),
            (
                "notifications/<notification_id>/action",
                self.notification_action,
                ["POST"],
            ),
        )
        for path, handler, methods in routes:
            register(
                f"/{PLUGIN_NAME}/{path}",
                handler,
                methods,
                f"Anime admin: {path}",
            )

    async def overview(self) -> object:
        return await self._read("overview")

    async def groups(self) -> object:
        return await self._read(
            "groups",
            query=self._query("query", ""),
            page=self._query_int("page", 1),
            page_size=self._query_int("page_size", 50),
        )

    async def subscriptions(self) -> object:
        return await self._read(
            "subscriptions",
            query=self._query("query", ""),
            page=self._query_int("page", 1),
            page_size=self._query_int("page_size", 50),
        )

    async def mappings(self) -> object:
        return await self._read(
            "mappings",
            page=self._query_int("page", 1),
            page_size=self._query_int("page_size", 50),
        )

    async def notifications(self) -> object:
        return await self._read(
            "notifications",
            status=self._query("status", ""),
            page=self._query_int("page", 1),
            page_size=self._query_int("page_size", 50),
        )

    async def sources(self) -> object:
        return await self._read("sources")

    async def jobs(self) -> object:
        return await self._read("jobs")

    async def controls(self) -> object:
        return await self._read("controls")

    async def update_group(self, group_id: str) -> object:
        payload = await self._json()
        expected_version = payload.pop("expected_version", None)
        if not isinstance(expected_version, int):
            return error_response("expected_version must be an integer")
        return await self._write(
            "update_group",
            group_id,
            expected_version=expected_version,
            changes=payload,
        )

    async def global_delivery(self) -> object:
        payload = await self._json()
        paused = payload.get("paused")
        if not isinstance(paused, bool):
            return error_response("paused must be a boolean")
        reason = payload.get("reason", "")
        if not isinstance(reason, str) or len(reason) > 256:
            return error_response("invalid reason")
        return await self._write("set_global_delivery", paused=paused, reason=reason)

    async def enqueue_job(self) -> object:
        payload = await self._json()
        job_type = payload.get("job_type")
        idempotency_key = payload.get("idempotency_key")
        parameters = payload.get("parameters", {})
        if not isinstance(job_type, str) or not isinstance(idempotency_key, str):
            return error_response("job_type and idempotency_key are required")
        if not isinstance(parameters, dict):
            return error_response("parameters must be an object")
        return await self._write(
            "enqueue_job",
            job_type,
            idempotency_key=idempotency_key,
            parameters=parameters,
        )

    async def cancel_subscription(self, subscription_id: str) -> object:
        return await self._write("cancel_subscription", subscription_id)

    async def review_mapping(self, mapping_id: str) -> object:
        payload = await self._json()
        decision = payload.get("decision")
        if not isinstance(decision, str):
            return error_response("decision is required")
        return await self._write("review_mapping", mapping_id, decision=decision)

    async def notification_action(self, notification_id: str) -> object:
        payload = await self._json()
        action = payload.get("action")
        if not isinstance(action, str):
            return error_response("action is required")
        return await self._write(
            "update_notification",
            notification_id,
            action=action,
            confirm_unknown=payload.get("confirm_unknown") is True,
        )

    async def _read(self, method: str, **kwargs: object) -> object:
        actor = self._actor()
        if actor is None:
            return error_response("authentication required", status_code=401)
        try:
            service = await self._service()
            result = await getattr(service, method)(**kwargs)
            return json_response(result)
        except (AdminValidationError, ValueError) as exc:
            return error_response(str(exc), status_code=400)

    async def _write(self, method: str, *args: object, **kwargs: object) -> object:
        actor = self._actor()
        if actor is None:
            return error_response("authentication required", status_code=401)
        lifecycle = await self._lifecycle_provider()
        if not bool(lifecycle.config.get("admin_page_writes_enabled", False)):
            return error_response("admin writes are disabled", status_code=403)
        try:
            service = AdminService(lifecycle.sessions)
            kwargs["actor"] = actor
            result = await getattr(service, method)(*args, **kwargs)
            return json_response({"ok": True, "result": result})
        except AdminNotFoundError as exc:
            return error_response(str(exc), status_code=404)
        except PolicyVersionConflictError:
            return error_response("version conflict; refresh and retry", status_code=409)
        except (AdminValidationError, ValueError) as exc:
            return error_response(str(exc), status_code=400)

    async def _service(self) -> AdminService:
        lifecycle = await self._lifecycle_provider()
        return AdminService(lifecycle.sessions)

    def _actor(self) -> str | None:
        username = getattr(request, "username", None)
        if not username:
            return None
        return sha256(str(username).encode()).hexdigest()[:16]

    async def _json(self) -> dict[str, object]:
        value = await request.json(default={})
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _query(name: str, default: str) -> str:
        value = request.query.get(name, default)
        return str(value)[:128]

    @staticmethod
    def _query_int(name: str, default: int) -> int:
        return int(request.query.get(name, default, type=int))


__all__ = ["PLUGIN_NAME", "AdminWebAPI"]
