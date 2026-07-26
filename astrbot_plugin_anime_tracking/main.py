"""AstrBot plugin: anime_tracking (v0.2.0).

This plugin bridges NapCat (OneBot 11) group events to the Anime Core
application layer. It is deliberately thin:

* lifecycle.py starts/stops the outbox consumer and database session.
* adapter.py converts AstrMessageEvent -> ChatContext -> Intent ->
  AnimeCore use case -> platform-neutral Reply.
* commands.py registers the /番剧 command group via AstrBot's
  built-in decorator.
* rendering.py maps a Reply into AstrBot/CQHTTP message components.

AstrBot SDK imports are guarded so the plugin directory compiles and
can be tested without installing the full AstrBot SDK in the Core
dev dependencies. At runtime the SDK must be present.
"""

from __future__ import annotations

from typing import Any

# Guard AstrBot imports — the SDK is provisioned by AstrBot's runtime,
# not by the Anime Core dev dependencies.
try:
    from astrbot.api.all import AstrBotPlugin, Context, register_event  # type: ignore[import-not-found]  # noqa: F401
except ModuleNotFoundError:
    AstrBotPlugin = object  # type: ignore[misc]  # noqa: N816
    Context = Any  # type: ignore[misc]  # noqa: N816

    def register_event(_name: str) -> Any:  # type: ignore[misc]  # noqa: N816
        return lambda fn: fn


from astrbot_plugin_anime_tracking.anime_tracking_plugin.lifecycle import (
    PluginLifecycle,
)


@register_event("on_initialize")
async def _on_initialize(context: Any) -> None:
    lifecycle = PluginLifecycle.from_context(context)
    await lifecycle.start()


@register_event("on_shutdown")
async def _on_shutdown(context: Any) -> None:
    lifecycle = PluginLifecycle.from_context(context)
    await lifecycle.shutdown()


class AnimeTrackingPlugin(AstrBotPlugin):  # type: ignore[name-defined]
    def __init__(self, context: Any) -> None:
        super().__init__(context)
        self.lifecycle = PluginLifecycle.from_context(context)


__all__ = ["AnimeTrackingPlugin"]