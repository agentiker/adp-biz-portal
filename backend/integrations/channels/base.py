"""Shared channel adapter and sender contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from core.delivery import InboundMessageInput


@dataclass(frozen=True)
class ChannelCapabilities:
    message_types: frozenset[str] = frozenset({"text"})
    supports_inbound: bool = True
    supports_outbound: bool = True
    supports_streaming: bool = False
    requires_signature: bool = False
    requires_encryption: bool = False
    reply_window_seconds: int | None = None


@dataclass(frozen=True)
class OutboundMessage:
    channel: str
    channel_instance_id: str
    external_conversation_id: str
    text: str
    idempotency_key: str
    trace_id: str
    metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class DeliveryReceipt:
    status: str
    provider_message_id: str | None = None
    uncertain: bool = False
    metadata: Mapping[str, Any] | None = None


@runtime_checkable
class ChannelAdapter(Protocol):
    channel: str
    channel_instance_id: str
    capabilities: ChannelCapabilities

    def normalize(self, **kwargs: Any) -> Any: ...


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
