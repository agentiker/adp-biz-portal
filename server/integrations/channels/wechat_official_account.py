"""Wechat Official Account callback adapter.

The adapter deliberately implements the platform-facing, plaintext XML
contract only.  AES callback mode and provider delivery are separate concerns
until a real account and protocol sample are available.
"""

from __future__ import annotations

import hashlib
import hmac
import time
import threading
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from core.delivery import InboundMessageInput
from core.error.platform import PlatformBadRequest
from integrations.channels.base import ChannelCapabilities, DeliveryReceipt, OutboundMessage


WECHAT_OFFICIAL_ACCOUNT = "wechat_official_account"
DEFAULT_REPLAY_WINDOW_SECONDS = 300
MAX_XML_BYTES = 256 * 1024


class WechatProtocolError(PlatformBadRequest):
    """Malformed or unauthenticated provider callback."""


class _ReplayGuard:
    def __init__(self, *, max_entries: int = 20_000) -> None:
        self._entries: dict[str, float] = {}
        self._lock = threading.Lock()
        self._max_entries = max_entries

    def check_and_mark(self, key: str, *, now: float, ttl: int) -> bool:
        with self._lock:
            cutoff = now - ttl
            self._entries = {item: stamp for item, stamp in self._entries.items() if stamp >= cutoff}
            if key in self._entries:
                return False
            if len(self._entries) >= self._max_entries:
                oldest = min(self._entries, key=self._entries.get)
                self._entries.pop(oldest, None)
            self._entries[key] = now
            return True


_replay_guard = _ReplayGuard()


def verify_signature(*, token: str, timestamp: str, nonce: str, signature: str) -> bool:
    if not all(isinstance(value, str) and value for value in (token, timestamp, nonce, signature)):
        return False
    if len(timestamp) > 32 or len(nonce) > 128 or len(signature) != 40:
        return False
    expected = hashlib.sha1("".join(sorted((token, timestamp, nonce))).encode("utf-8")).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


def _timestamp(value: Any, *, now: float, window_seconds: int) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise WechatProtocolError("微信回调时间戳格式不正确") from exc
    if abs(now - parsed) > window_seconds:
        raise WechatProtocolError("微信回调已超出允许时间窗口")
    return parsed


def _xml_value(root: ET.Element, name: str, *, required: bool = False) -> str:
    value = root.findtext(name)
    value = value.strip() if isinstance(value, str) else ""
    if required and not value:
        raise WechatProtocolError(f"微信回调缺少{name}")
    return value


def _parse_xml(body: bytes) -> ET.Element:
    if not isinstance(body, (bytes, bytearray)) or not body or len(body) > MAX_XML_BYTES:
        raise WechatProtocolError("微信回调 XML 无效")
    # ElementTree does not resolve external entities, but reject DTD/entity
    # declarations explicitly so the boundary remains safe if the parser is
    # ever replaced.
    lowered = bytes(body).lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise WechatProtocolError("微信回调 XML 不允许实体声明")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise WechatProtocolError("微信回调 XML 无效") from exc
    if root.tag.rsplit("}", 1)[-1] != "xml":
        raise WechatProtocolError("微信回调 XML 根节点无效")
    return root


@dataclass(frozen=True)
class WechatInboundEnvelope:
    message: InboundMessageInput
    task_payload: Mapping[str, Any]
    open_id: str
    created_at: int


class WechatOfficialAccountAdapter:
    channel = WECHAT_OFFICIAL_ACCOUNT
    capabilities = ChannelCapabilities(
        message_types=frozenset({"text", "event"}),
        supports_inbound=True,
        supports_outbound=True,
        supports_streaming=False,
        requires_signature=True,
        requires_encryption=False,
        reply_window_seconds=48 * 60 * 60,
    )

    def __init__(self, *, channel_instance_id: str, token: str, replay_window_seconds: int = DEFAULT_REPLAY_WINDOW_SECONDS):
        if not isinstance(channel_instance_id, str) or not channel_instance_id.strip():
            raise ValueError("channel_instance_id is required")
        if not isinstance(token, str) or not token.strip():
            raise ValueError("token is required")
        self.channel_instance_id = channel_instance_id.strip()
        self.token = token
        self.replay_window_seconds = replay_window_seconds

    def verify_callback(self, *, signature: str, timestamp: str, nonce: str, now: float | None = None) -> None:
        current = time.time() if now is None else now
        parsed = _timestamp(timestamp, now=current, window_seconds=self.replay_window_seconds)
        if not verify_signature(token=self.token, timestamp=str(parsed), nonce=nonce, signature=signature):
            raise WechatProtocolError("微信回调签名无效")
        replay_key = hashlib.sha256(f"{self.channel_instance_id}:{parsed}:{nonce}:{signature}".encode()).hexdigest()
        if not _replay_guard.check_and_mark(replay_key, now=current, ttl=self.replay_window_seconds):
            raise WechatProtocolError("微信回调重复提交")

    def verification_echo(self, *, signature: str, timestamp: str, nonce: str, echostr: str, now: float | None = None) -> str:
        self.verify_callback(signature=signature, timestamp=timestamp, nonce=nonce, now=now)
        if not isinstance(echostr, str) or len(echostr) > 512:
            raise WechatProtocolError("echostr格式不正确")
        return echostr

    def normalize_xml(self, *, body: bytes, trace_id: str, now: float | None = None) -> WechatInboundEnvelope:
        root = _parse_xml(body)
        msg_type = _xml_value(root, "MsgType", required=True).lower()
        open_id = _xml_value(root, "FromUserName", required=True)
        to_user = _xml_value(root, "ToUserName", required=True)
        created_at = _timestamp(_xml_value(root, "CreateTime", required=True), now=time.time() if now is None else now, window_seconds=24 * 60 * 60)
        msg_id = _xml_value(root, "MsgId")
        content = _xml_value(root, "Content") if msg_type == "text" else _xml_value(root, "Event")
        if msg_type == "text" and not content:
            raise WechatProtocolError("微信文本消息缺少Content")
        if not msg_id:
            digest = hashlib.sha256(f"{to_user}|{open_id}|{created_at}|{msg_type}|{content}".encode()).hexdigest()
            msg_id = f"generated-{digest}"
        external_conversation_id = f"{self.channel_instance_id}:{open_id}"
        return WechatInboundEnvelope(
            message=InboundMessageInput(
                channel_instance_id=self.channel_instance_id,
                external_message_id=msg_id,
                external_conversation_id=external_conversation_id,
                sender_identity_id=open_id,
                text=content,
                trace_id=trace_id,
                message_type=msg_type,
                payload={"channel": self.channel, "toUserName": to_user, "protocol": "wechat.official-account.xml.v1"},
            ),
            task_payload={"channel": self.channel, "traceId": trace_id, "externalIdentityId": open_id},
            open_id=open_id,
            created_at=created_at,
        )

    def normalize(self, **kwargs: Any) -> WechatInboundEnvelope:
        """Registry-compatible normalization entry point."""
        return self.normalize_xml(**kwargs)


class WechatOfficialAccountSender:
    channel = WECHAT_OFFICIAL_ACCOUNT

    def __init__(self, *, channel_instance_id: str):
        self.channel_instance_id = channel_instance_id

    async def send(self, *, message: OutboundMessage | None = None, payload: Mapping[str, Any] | None = None) -> DeliveryReceipt:
        # The delivery worker currently passes its persisted payload; keeping
        # the typed message form available preserves the channel contract for
        # direct callers and future provider transports.
        if message is None:
            payload = payload or {}
            message = OutboundMessage(
                channel=self.channel,
                channel_instance_id=self.channel_instance_id,
                external_conversation_id=str(payload.get("externalConversationId") or ""),
                text=str(payload.get("summary") or ""),
                idempotency_key=str(payload.get("deliveryIdempotencyKey") or ""),
                trace_id=str(payload.get("traceId") or ""),
                metadata=payload,
            )
        metadata = dict(message.metadata or {})
        deadline = metadata.get("replyWindowExpiresAt")
        if isinstance(deadline, str):
            try:
                expires = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                if expires <= datetime.now(timezone.utc):
                    return DeliveryReceipt(status="failed", uncertain=False, metadata={"reason": "reply_window_expired"})
            except ValueError:
                return DeliveryReceipt(status="failed", uncertain=False, metadata={"reason": "invalid_reply_window"})
        return DeliveryReceipt(status="uncertain", uncertain=True, metadata={"reason": "provider_transport_not_configured"})
