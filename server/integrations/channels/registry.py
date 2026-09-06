"""In-process registry for channel protocol adapters."""

from __future__ import annotations

from typing import Any


class ChannelRegistryError(ValueError):
    pass


class ChannelAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[tuple[str, str], Any] = {}

    def register(self, adapter: Any, *, replace: bool = False) -> Any:
        channel = str(getattr(adapter, "channel", "")).strip()
        instance_id = str(getattr(adapter, "channel_instance_id", "")).strip()
        if not channel or not instance_id or not callable(getattr(adapter, "normalize", None)):
            raise ChannelRegistryError("channel adapter requires channel, channel_instance_id and normalize()")
        key = (channel, instance_id)
        if key in self._adapters and not replace:
            raise ChannelRegistryError(f"channel adapter already registered: {channel}/{instance_id}")
        self._adapters[key] = adapter
        return adapter

    def get(self, channel: str, instance_id: str) -> Any:
        key = (str(channel).strip(), str(instance_id).strip())
        adapter = self._adapters.get(key)
        if adapter is None:
            raise ChannelRegistryError(f"channel adapter not registered: {key[0]}/{key[1]}")
        return adapter

    def list(self) -> tuple[Any, ...]:
        return tuple(self._adapters.values())


channel_registry = ChannelAdapterRegistry()


def register_default_adapters() -> ChannelAdapterRegistry:
    from integrations.channels.web import WebChannelAdapter

    key = (WebChannelAdapter.channel, WebChannelAdapter.channel_instance_id)
    if not any((getattr(item, "channel", None), getattr(item, "channel_instance_id", None)) == key for item in channel_registry.list()):
        channel_registry.register(WebChannelAdapter())
    return channel_registry


def register_wechat_official_account(adapter: Any, *, replace: bool = False) -> Any:
    """Register a configured service-account adapter explicitly.

    Tokens are deployment secrets, so the default registry never constructs a
    service-account adapter without a configured credential.
    """
    return channel_registry.register(adapter, replace=replace)
