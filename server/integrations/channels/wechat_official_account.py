"""Wechat Official Account callback adapter.

Both plaintext XML and WeChat's ``安全模式`` callback envelope are handled at
this boundary. Provider delivery remains a separate concern because inbound
callbacks can be acknowledged before an outbound transport is configured.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import struct
import time
import threading
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

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
        # The adapter accepts both modes. A configured EncodingAESKey enables
        # encrypted callbacks while legacy token-only credentials stay valid.
        requires_encryption=False,
        reply_window_seconds=48 * 60 * 60,
    )

    def __init__(
        self,
        *,
        channel_instance_id: str,
        token: str,
        app_id: str | None = None,
        encoding_aes_key: str | None = None,
        replay_window_seconds: int = DEFAULT_REPLAY_WINDOW_SECONDS,
    ):
        if not isinstance(channel_instance_id, str) or not channel_instance_id.strip():
            raise ValueError("channel_instance_id is required")
        if not isinstance(token, str) or not token.strip():
            raise ValueError("token is required")
        self.channel_instance_id = channel_instance_id.strip()
        self.token = token
        self.app_id = app_id.strip() if isinstance(app_id, str) and app_id.strip() else None
        self._aes_key = self._decode_aes_key(encoding_aes_key) if encoding_aes_key else None
        if self._aes_key is not None and not self.app_id:
            raise ValueError("app_id is required for encrypted WeChat callbacks")
        self.replay_window_seconds = replay_window_seconds

    @staticmethod
    def _decode_aes_key(value: str | None) -> bytes:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("encoding_aes_key is required")
        # WeChat displays a 43-character base64 value without the final '='.
        encoded = value.strip()
        if len(encoded) not in (43, 44):
            raise ValueError("encoding_aes_key has an invalid length")
        try:
            key = base64.b64decode(encoded + "=" * (-len(encoded) % 4), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("encoding_aes_key is not valid base64") from exc
        if len(key) != 32:
            raise ValueError("encoding_aes_key must decode to 32 bytes")
        return key

    def verify_callback(self, *, signature: str, timestamp: str, nonce: str, now: float | None = None) -> None:
        current = time.time() if now is None else now
        parsed = _timestamp(timestamp, now=current, window_seconds=self.replay_window_seconds)
        if not verify_signature(token=self.token, timestamp=str(parsed), nonce=nonce, signature=signature):
            raise WechatProtocolError("微信回调签名无效")
        replay_key = hashlib.sha256(f"{self.channel_instance_id}:{parsed}:{nonce}:{signature}".encode()).hexdigest()
        if not _replay_guard.check_and_mark(replay_key, now=current, ttl=self.replay_window_seconds):
            raise WechatProtocolError("微信回调重复提交")

    def verify_encrypted_callback(
        self,
        *,
        msg_signature: str,
        timestamp: str,
        nonce: str,
        encrypt: str,
        now: float | None = None,
    ) -> None:
        if self._aes_key is None:
            raise WechatProtocolError("微信安全模式未配置EncodingAESKey")
        current = time.time() if now is None else now
        parsed = _timestamp(timestamp, now=current, window_seconds=self.replay_window_seconds)
        if not isinstance(encrypt, str) or not encrypt or len(encrypt) > 512 * 1024:
            raise WechatProtocolError("微信加密回调内容无效")
        expected = hashlib.sha1("".join(sorted((self.token, str(parsed), nonce, encrypt))).encode("utf-8")).hexdigest()
        if not isinstance(msg_signature, str) or not hmac.compare_digest(expected, msg_signature.lower()):
            raise WechatProtocolError("微信加密回调签名无效")
        replay_key = hashlib.sha256(
            f"{self.channel_instance_id}:aes:{parsed}:{nonce}:{msg_signature}:{hashlib.sha256(encrypt.encode()).hexdigest()}".encode()
        ).hexdigest()
        if not _replay_guard.check_and_mark(replay_key, now=current, ttl=self.replay_window_seconds):
            raise WechatProtocolError("微信回调重复提交")

    @staticmethod
    def extract_encrypted(body: bytes) -> str:
        root = _parse_xml(body)
        encrypted = _xml_value(root, "Encrypt", required=True)
        if len(encrypted) > 512 * 1024:
            raise WechatProtocolError("微信加密回调内容过大")
        return encrypted

    def decrypt_xml(self, encrypt: str) -> bytes:
        """Decrypt the WeChat AES-256-CBC envelope and validate its AppID."""
        if self._aes_key is None or not self.app_id:
            raise WechatProtocolError("微信安全模式凭据不完整")
        try:
            ciphertext = base64.b64decode(encrypt, validate=True)
            decryptor = Cipher(algorithms.AES(self._aes_key), modes.CBC(self._aes_key[:16])).decryptor()
            padded = decryptor.update(ciphertext) + decryptor.finalize()
        except (ValueError, binascii.Error) as exc:
            raise WechatProtocolError("微信加密回调无法解密") from exc
        if not padded or len(padded) % 32:
            raise WechatProtocolError("微信加密回调填充无效")
        pad_length = padded[-1]
        if not 1 <= pad_length <= 32 or padded[-pad_length:] != bytes([pad_length]) * pad_length:
            raise WechatProtocolError("微信加密回调填充无效")
        payload = padded[:-pad_length]
        if len(payload) < 20:
            raise WechatProtocolError("微信加密回调内容不完整")
        message_length = struct.unpack("!I", payload[16:20])[0]
        message_end = 20 + message_length
        if message_end > len(payload):
            raise WechatProtocolError("微信加密回调消息长度无效")
        xml_body = payload[20:message_end]
        try:
            payload_app_id = payload[message_end:].decode("utf-8")
            xml_body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WechatProtocolError("微信加密回调编码无效") from exc
        if payload_app_id != self.app_id:
            raise WechatProtocolError("微信加密回调AppID不匹配")
        return xml_body

    def verification_echo(
        self,
        *,
        signature: str,
        timestamp: str,
        nonce: str,
        echostr: str,
        msg_signature: str | None = None,
        encrypted: bool = False,
        now: float | None = None,
    ) -> str:
        if not isinstance(echostr, str) or len(echostr) > 512 * 1024:
            raise WechatProtocolError("echostr格式不正确")
        if encrypted or msg_signature:
            self.verify_encrypted_callback(
                msg_signature=msg_signature or signature,
                timestamp=timestamp,
                nonce=nonce,
                encrypt=echostr,
                now=now,
            )
            try:
                return self.decrypt_xml(echostr).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise WechatProtocolError("echostr解密结果无效") from exc
        self.verify_callback(signature=signature, timestamp=timestamp, nonce=nonce, now=now)
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
