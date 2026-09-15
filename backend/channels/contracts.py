"""Provider-neutral data contracts shared by core and channel adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping


@dataclass(frozen=True)
class InboundMessageInput:
    channel_instance_id: str
    external_message_id: str
    external_conversation_id: str
    sender_identity_id: str
    text: str | None
    trace_id: str
    message_type: str = "text"
    payload: Mapping[str, Any] | None = None
    reply_window_expires_at: datetime | None = None


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
