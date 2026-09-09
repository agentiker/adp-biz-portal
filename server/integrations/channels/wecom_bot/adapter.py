"""企业微信智能机器人 (WeCom smart robot) message normalization.

Owns only the message model: turning one decrypted ``aibot_msg_callback``
message into a normalized inbound envelope. Verification/decryption is
crypto_json; the WS connection, streaming and inline agent run live in the
gateway. No network, no DB here.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from core.delivery import InboundMessageInput
from integrations.channels.base import ChannelCapabilities


WECOM_BOT = "wecom_bot"
# The AI bot has a generous interaction window; kept conservative for preflight.
WECOM_BOT_REPLY_WINDOW_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class WecomBotInboundEnvelope:
    message: InboundMessageInput
    task_payload: Mapping[str, Any]
    msgid: str
    chat_id: str
    chat_type: str
    from_userid: str
    stream_id: str

    def get_launcher_id(self) -> str:
        # A group chat is scoped by chat id; a 1:1 chat by the user id.
        return self.chat_id if self.chat_type == "group" and self.chat_id else self.from_userid


class WecomBotAdapter:
    channel = WECOM_BOT
    capabilities = ChannelCapabilities(
        message_types=frozenset({"text"}),
        supports_inbound=True,
        supports_outbound=True,
        supports_streaming=True,
        requires_signature=True,
        requires_encryption=True,
        reply_window_seconds=WECOM_BOT_REPLY_WINDOW_SECONDS,
    )

    def __init__(self, *, channel_instance_id: str, corp_id: str, token: str, encoding_aes_key: str):
        if not isinstance(channel_instance_id, str) or not channel_instance_id.strip():
            raise ValueError("channel_instance_id is required")
        if not isinstance(corp_id, str) or not corp_id.strip():
            raise ValueError("corp_id is required")
        if not isinstance(token, str) or not token.strip():
            raise ValueError("token is required")
        # Import here so a missing crypto dependency surfaces at construction.
        from integrations.channels._wechat.crypto import decode_aes_key

        self.channel_instance_id = channel_instance_id.strip()
        self.corp_id = corp_id.strip()
        self.token = token
        self.aes_key = decode_aes_key(encoding_aes_key)

    def normalize_message(
        self, msg: Mapping[str, Any], *, trace_id: str, now: float | None = None
    ) -> WecomBotInboundEnvelope | None:
        """Normalize one decrypted bot message; return None for non-text input."""
        if not isinstance(msg, Mapping) or msg.get("msgtype") != "text":
            return None
        msgid = str(msg.get("msgid") or "").strip()
        chat_type = str(msg.get("chattype") or "single").strip() or "single"
        chat_id = str(msg.get("chatid") or "").strip()
        from_userid = str(((msg.get("from") or {}).get("userid")) or "").strip()
        content = str(((msg.get("text") or {}).get("content")) or "").strip()
        stream_id = str(((msg.get("stream") or {}).get("id")) or "").strip()
        if not from_userid or not content:
            return None
        if not msgid:
            digest = hashlib.sha256(f"{chat_id}|{from_userid}|{content}".encode()).hexdigest()
            msgid = f"generated-{digest}"
        scope = chat_id if (chat_type == "group" and chat_id) else from_userid
        received_at = datetime.fromtimestamp(int(time.time() if now is None else now), tz=timezone.utc).replace(tzinfo=None)
        return WecomBotInboundEnvelope(
            message=InboundMessageInput(
                channel_instance_id=self.channel_instance_id,
                external_message_id=msgid,
                external_conversation_id=f"{self.channel_instance_id}:{scope}",
                sender_identity_id=from_userid,
                text=content,
                trace_id=trace_id,
                message_type="text",
                payload={
                    "channel": self.channel,
                    "chatId": chat_id,
                    "chatType": chat_type,
                    "protocol": "wecom.aibot.ws.v1",
                },
                reply_window_expires_at=received_at + timedelta(seconds=WECOM_BOT_REPLY_WINDOW_SECONDS),
            ),
            task_payload={"channel": self.channel, "traceId": trace_id, "externalIdentityId": from_userid},
            msgid=msgid,
            chat_id=chat_id,
            chat_type=chat_type,
            from_userid=from_userid,
            stream_id=stream_id,
        )

    def normalize(self, **kwargs: Any) -> WecomBotInboundEnvelope | None:
        return self.normalize_message(**kwargs)
