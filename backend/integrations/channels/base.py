"""Shared channel adapter and sender contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from channels.contracts import ChannelCapabilities, DeliveryReceipt, InboundMessageInput, OutboundMessage


@runtime_checkable
class ChannelAdapter(Protocol):
    channel: str
    channel_instance_id: str
    capabilities: ChannelCapabilities

    def normalize(self, **kwargs: Any) -> Any: ...

    def get_launcher_id(self, envelope: Any) -> str: ...


def launcher_id_from_envelope(envelope: Any, *, default: str) -> str:
    """Return an adapter's session-scope key, or a default sender identity.

    A channel whose session is narrower than the raw sender (WeChat 客服 keys a
    session by ``open_kfid|external_userid``, group chats by chat id) exposes it
    via ``get_launcher_id``; adapters without one fall back to the sender.
    """
    getter = getattr(envelope, "get_launcher_id", None)
    if callable(getter):
        value = getter()
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default


@runtime_checkable
class ChannelSender(Protocol):
    channel: str
    channel_instance_id: str

    async def send(self, *, message: OutboundMessage) -> DeliveryReceipt | Mapping[str, Any] | None: ...


def inbound_from_envelope(envelope: Any) -> InboundMessageInput:
    message = getattr(envelope, "message", None)
    if not isinstance(message, InboundMessageInput):
        raise TypeError("channel adapter returned an invalid inbound envelope")
    return message
