"""Normalize authenticated website messages for the platform delivery worker.

The browser is a channel client, not an authority.  This adapter deliberately
derives all identity and scope fields from ``PlatformContext`` and only accepts
message content plus a retry-stable message identifier from the request.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from core.delivery import InboundMessageInput
from core.error.platform import PlatformBadRequest
from core.platform import PlatformContext
from integrations.channels.base import ChannelCapabilities


WEB_CHANNEL = "web"
WEB_CHANNEL_INSTANCE_ID = "web-portal"
WEB_MESSAGE_TYPE = "text"


def _required_text(value: Any, *, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise PlatformBadRequest(f"{field}格式不正确")
    normalized = value.strip()
    if not normalized or len(normalized) > limit:
        raise PlatformBadRequest(f"{field}格式不正确")
    return normalized


def _optional_message_id(value: Any) -> str:
    if value in (None, ""):
        # A caller that wants retry de-duplication should send the same
        # X-Message-Id/body messageId on every retry.  A missing ID remains a
        # valid one-shot website message and receives a fresh stable ID.
        return uuid.uuid4().hex
    return _required_text(value, field="消息 ID", limit=255)


def _conversation_id(value: Any) -> str | None:
    if value in (None, ""):
        return None
    normalized = _required_text(value, field="会话 ID", limit=64)
    try:
        return str(uuid.UUID(normalized))
    except ValueError as exc:
        raise PlatformBadRequest("会话 ID 格式不正确") from exc


@dataclass(frozen=True)
class WebInboundEnvelope:
    """The normalized callback and the trusted task payload derived from it."""

    message: InboundMessageInput
    task_payload: Mapping[str, Any]
    conversation_id: str | None


class WebChannelAdapter:
    """Convert one authenticated portal request into a durable inbound task."""

    channel = WEB_CHANNEL
    channel_instance_id = WEB_CHANNEL_INSTANCE_ID
    capabilities = ChannelCapabilities(message_types=frozenset({WEB_MESSAGE_TYPE}))

    def normalize(
        self,
        *,
        context: PlatformContext,
        text: Any,
        trace_id: Any,
        message_id: Any = None,
        conversation_id: Any = None,
    ) -> WebInboundEnvelope:
        normalized_text = _required_text(text, field="消息文本", limit=10000)
        normalized_trace = _required_text(trace_id, field="Trace ID", limit=64)
        external_message_id = _optional_message_id(message_id)
        normalized_conversation_id = _conversation_id(conversation_id)

        user_id = str(context.user.Id)
        account_id = str(context.account.Id)
        session_id = str(context.session.Id)
        # An external conversation is still needed for FIFO before a new
        # platform conversation row exists.  The worker replaces this with a
        # server-created conversation ID during processing.
        external_conversation_id = normalized_conversation_id or f"session:{session_id}"
        task_payload = {
            "platformUserId": user_id,
            "platformSessionId": session_id,
            "enterpriseId": None,
            "conversationId": normalized_conversation_id,
            "channel": self.channel,
            "traceId": normalized_trace,
            "agentId": "platform-default",
            "accountId": account_id,
            "source": "portal",
        }
        return WebInboundEnvelope(
            message=InboundMessageInput(
                channel_instance_id=self.channel_instance_id,
                external_message_id=external_message_id,
                external_conversation_id=external_conversation_id,
                sender_identity_id=user_id,
                text=normalized_text,
                trace_id=normalized_trace,
                message_type=WEB_MESSAGE_TYPE,
                payload={
                    "channel": self.channel,
                    "channelInstanceId": self.channel_instance_id,
                    "accountId": account_id,
                    "protocol": "platform-web.v1",
                },
            ),
            task_payload=task_payload,
            conversation_id=normalized_conversation_id,
        )


def normalize_web_inbound(**kwargs: Any) -> WebInboundEnvelope:
    """Small functional entry point for adapters and tests."""

    return WebChannelAdapter().normalize(**kwargs)
