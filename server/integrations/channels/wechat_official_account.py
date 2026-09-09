"""Wechat Official Account callback adapter.

Both plaintext XML and WeChat's ``安全模式`` callback envelope are handled at
this boundary. Provider delivery remains a separate concern because inbound
callbacks can be acknowledged before an outbound transport is configured.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from core.delivery import InboundMessageInput
from integrations.channels._wechat.crypto import (
    WechatProtocolError,
    cdata as _cdata,
    check_timestamp as _timestamp,
    compute_msg_signature,
    decode_aes_key,
    decrypt_envelope,
    encrypt_payload,
    extract_encrypted_xml,
    parse_xml as _parse_xml,
    replay_guard as _replay_guard,
    verify_msg_signature,
    verify_signature,
    xml_value as _xml_value,
)
from integrations.channels.base import ChannelCapabilities, DeliveryReceipt, OutboundMessage
from integrations.channels.text_format import to_plain_text
from integrations.channels.wechat_transport import WechatSendError


WECHAT_OFFICIAL_ACCOUNT = "wechat_official_account"
DEFAULT_REPLAY_WINDOW_SECONDS = 300
MAX_REPLY_CHARS = 2000


@dataclass(frozen=True)
class WechatInboundEnvelope:
    message: InboundMessageInput
    task_payload: Mapping[str, Any]
    open_id: str
    created_at: int
    to_user: str


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
        self._aes_key = decode_aes_key(encoding_aes_key) if encoding_aes_key else None
        if self._aes_key is not None and not self.app_id:
            raise ValueError("app_id is required for encrypted WeChat callbacks")
        self.replay_window_seconds = replay_window_seconds

    def verify_callback(self, *, signature: str, timestamp: str, nonce: str, now: float | None = None) -> str:
        """Verify a plaintext callback and return its durable replay key."""
        current = time.time() if now is None else now
        parsed = _timestamp(timestamp, now=current, window_seconds=self.replay_window_seconds)
        if not verify_signature(token=self.token, timestamp=str(parsed), nonce=nonce, signature=signature):
            raise WechatProtocolError("微信回调签名无效")
        replay_key = hashlib.sha256(f"{self.channel_instance_id}:{parsed}:{nonce}:{signature}".encode()).hexdigest()
        if not _replay_guard.check_and_mark(replay_key, now=current, ttl=self.replay_window_seconds):
            raise WechatProtocolError("微信回调重复提交")
        return replay_key

    def verify_encrypted_callback(
        self,
        *,
        msg_signature: str,
        timestamp: str,
        nonce: str,
        encrypt: str,
        now: float | None = None,
    ) -> str:
        """Verify an encrypted callback and return its durable replay key."""
        if self._aes_key is None:
            raise WechatProtocolError("微信安全模式未配置EncodingAESKey")
        current = time.time() if now is None else now
        parsed = _timestamp(timestamp, now=current, window_seconds=self.replay_window_seconds)
        if not isinstance(encrypt, str) or not encrypt or len(encrypt) > 512 * 1024:
            raise WechatProtocolError("微信加密回调内容无效")
        if not verify_msg_signature(
            token=self.token, timestamp=str(parsed), nonce=nonce, encrypt=encrypt, msg_signature=msg_signature
        ):
            raise WechatProtocolError("微信加密回调签名无效")
        replay_key = hashlib.sha256(
            f"{self.channel_instance_id}:aes:{parsed}:{nonce}:{msg_signature}:{hashlib.sha256(encrypt.encode()).hexdigest()}".encode()
        ).hexdigest()
        if not _replay_guard.check_and_mark(replay_key, now=current, ttl=self.replay_window_seconds):
            raise WechatProtocolError("微信回调重复提交")
        return replay_key

    @staticmethod
    def extract_encrypted(body: bytes) -> str:
        return extract_encrypted_xml(body)

    def decrypt_xml(self, encrypt: str) -> bytes:
        """Decrypt the WeChat AES-256-CBC envelope and validate its AppID."""
        if self._aes_key is None or not self.app_id:
            raise WechatProtocolError("微信安全模式凭据不完整")
        return decrypt_envelope(
            aes_key=self._aes_key,
            encrypt=encrypt,
            expected_receiver_id=self.app_id,
            receiver_label="AppID",
        )

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
        received_at = datetime.fromtimestamp(created_at, tz=timezone.utc).replace(tzinfo=None)
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
                # The customer-service message window is measured from the
                # user's message, not from when the platform finishes working.
                reply_window_expires_at=(
                    received_at + timedelta(seconds=self.capabilities.reply_window_seconds)
                    if self.capabilities.reply_window_seconds
                    else None
                ),
            ),
            task_payload={"channel": self.channel, "traceId": trace_id, "externalIdentityId": open_id},
            open_id=open_id,
            created_at=created_at,
            to_user=to_user,
        )

    def normalize(self, **kwargs: Any) -> WechatInboundEnvelope:
        """Registry-compatible normalization entry point."""
        return self.normalize_xml(**kwargs)

    def build_text_reply(
        self,
        *,
        to_open_id: str,
        from_account: str,
        content: str,
        now: float | None = None,
    ) -> str:
        """Build the passive text reply returned in the callback response.

        A passive reply is the only way to answer a sender the platform will
        not process further (unbound identity, binding result). It keeps the
        provider contract intact: the callback still answers 200 with a body
        WeChat understands, so the account is not marked as failing.
        """
        created = int(time.time() if now is None else now)
        return (
            "<xml>"
            f"<ToUserName><![CDATA[{_cdata(to_open_id, field='接收者')}]]></ToUserName>"
            f"<FromUserName><![CDATA[{_cdata(from_account, field='发送者')}]]></FromUserName>"
            f"<CreateTime>{created}</CreateTime>"
            "<MsgType><![CDATA[text]]></MsgType>"
            f"<Content><![CDATA[{_cdata(content, field='回复内容', max_length=MAX_REPLY_CHARS)}]]></Content>"
            "</xml>"
        )

    def encrypt_reply(self, plain_xml: str, *, now: float | None = None, nonce: str | None = None) -> str:
        """Wrap a passive reply in WeChat's 安全模式 envelope."""
        if self._aes_key is None or not self.app_id:
            raise WechatProtocolError("微信安全模式凭据不完整")
        if not isinstance(plain_xml, str) or not plain_xml:
            raise WechatProtocolError("微信回复内容无效")
        encrypted = encrypt_payload(aes_key=self._aes_key, receiver_id=self.app_id, plain=plain_xml)
        timestamp = str(int(time.time() if now is None else now))
        reply_nonce = nonce if isinstance(nonce, str) and nonce.strip() else secrets.token_hex(8)
        signature = compute_msg_signature(
            token=self.token, timestamp=timestamp, nonce=reply_nonce, encrypt=encrypted
        )
        return (
            "<xml>"
            f"<Encrypt><![CDATA[{encrypted}]]></Encrypt>"
            f"<MsgSignature><![CDATA[{signature}]]></MsgSignature>"
            f"<TimeStamp>{timestamp}</TimeStamp>"
            f"<Nonce><![CDATA[{reply_nonce}]]></Nonce>"
            "</xml>"
        )

    def build_reply(
        self,
        *,
        to_open_id: str,
        from_account: str,
        content: str,
        encrypted: bool = False,
        now: float | None = None,
        nonce: str | None = None,
    ) -> str:
        """Build a passive reply, encrypting it when the callback was encrypted."""
        plain = self.build_text_reply(
            to_open_id=to_open_id,
            from_account=from_account,
            content=content,
            now=now,
        )
        if not encrypted:
            return plain
        return self.encrypt_reply(plain, now=now, nonce=nonce)


class WechatOfficialAccountSender:
    """Deliver a platform reply as a WeChat customer-service message.

    A transport is optional on purpose: without app credentials the sender
    reports an uncertain outcome instead of claiming a delivery that never
    happened.
    """

    channel = WECHAT_OFFICIAL_ACCOUNT

    def __init__(self, *, channel_instance_id: str, transport: Any = None):
        self.channel_instance_id = channel_instance_id
        self._transport = transport

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
        if self._transport is None:
            return DeliveryReceipt(status="uncertain", uncertain=True, metadata={"reason": "provider_transport_not_configured"})

        open_id = self._open_id(message, metadata)
        if open_id is None:
            return DeliveryReceipt(status="failed", uncertain=False, metadata={"reason": "missing_recipient_identity"})
        # The account renders text messages as plain text, so markdown markup
        # would show its raw asterisks and hashes. The streamed path cleaned
        # each chunk; the single complete answer is cleaned the same way here.
        content = to_plain_text(message.text) or (message.text or "")
        try:
            return await self._transport.send_text(open_id=open_id, content=content)
        except WechatSendError as exc:
            # A malformed outbound message is a platform bug, not a provider
            # failure; retrying the same payload cannot help.
            return DeliveryReceipt(status="failed", uncertain=False, metadata={"reason": str(exc)})

    async def send_result_card(
        self,
        *,
        payload: Mapping[str, Any],
        title: str,
        description: str,
        url: str,
    ) -> DeliveryReceipt:
        """Send the structured result as a rich card.

        A text message cannot render structure, so the record-worthy view of a
        result — title, summary and a link to the full evidence — goes out as a
        ``news`` article. Returns an uncertain receipt when no transport is
        configured, exactly like a text send.
        """
        if self._transport is None:
            return DeliveryReceipt(status="uncertain", uncertain=True, metadata={"reason": "provider_transport_not_configured"})
        send_news = getattr(self._transport, "send_news", None)
        if send_news is None:
            return DeliveryReceipt(status="failed", uncertain=False, metadata={"reason": "card_not_supported"})
        conversation = str(payload.get("externalConversationId") or "")
        prefix = f"{self.channel_instance_id}:"
        open_id = conversation[len(prefix):].strip() if conversation.startswith(prefix) else ""
        if not open_id:
            return DeliveryReceipt(status="failed", uncertain=False, metadata={"reason": "missing_recipient_identity"})
        try:
            return await send_news(open_id=open_id, title=title, description=description, url=url)
        except WechatSendError as exc:
            return DeliveryReceipt(status="failed", uncertain=False, metadata={"reason": str(exc)})

    def _open_id(self, message: OutboundMessage, metadata: Mapping[str, Any]) -> str | None:
        """Recover the recipient OpenID from the persisted reply payload.

        ``externalConversationId`` is ``<instance>:<openid>`` as produced by
        ``normalize_xml``; the sender never accepts a recipient from anywhere
        the browser or the model could influence.
        """
        conversation = message.external_conversation_id or str(metadata.get("externalConversationId") or "")
        prefix = f"{self.channel_instance_id}:"
        if conversation.startswith(prefix):
            candidate = conversation[len(prefix):].strip()
            return candidate or None
        return None
