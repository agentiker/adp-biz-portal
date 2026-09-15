"""WeChat 客服 (WeCom Customer Service) callback adapter.

The callback is only a NOTIFICATION: it is verified and decrypted to recover a
short-lived pull ``Token`` and the ``OpenKfId``; the actual messages are pulled
separately via ``kf/sync_msg`` (see wechat_kf.transport / the worker pull task).
This module owns verification, notification extraction and per-item
normalization only — no network, no cursor, no DB.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from channels.contracts import InboundMessageInput
from integrations.channels._wechat.crypto import (
    WechatProtocolError,
    check_timestamp,
    decode_aes_key,
    decrypt_envelope,
    extract_encrypted_xml,
    replay_guard,
    verify_msg_signature,
)
from integrations.channels.base import ChannelCapabilities


WECHAT_KF = "wechat_kf"
DEFAULT_REPLAY_WINDOW_SECONDS = 300
# WeChat 客服 replies stay open for a long support window; the exact bound is a
# provider policy, kept conservative here for the reply-window preflight.
KF_REPLY_WINDOW_SECONDS = 48 * 60 * 60


@dataclass(frozen=True)
class WechatKfInboundEnvelope:
    message: InboundMessageInput
    task_payload: Mapping[str, Any]
    open_kfid: str
    external_userid: str

    def get_launcher_id(self) -> str:
        # A 客服 session is scoped by the service account AND the external user,
        # not by either alone.
        return f"{self.open_kfid}|{self.external_userid}"


def _envelope_encrypt(body: bytes) -> str:
    """Extract the ``Encrypt`` blob from an XML or JSON callback envelope."""
    if not isinstance(body, (bytes, bytearray)) or not body:
        raise WechatProtocolError("微信客服回调为空")
    stripped = bytes(body).lstrip()
    if stripped[:1] == b"{":
        try:
            payload = json.loads(bytes(body).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise WechatProtocolError("微信客服回调 JSON 无效") from exc
        encrypt = payload.get("encrypt") or payload.get("Encrypt")
        if not isinstance(encrypt, str) or not encrypt:
            raise WechatProtocolError("微信客服回调缺少 Encrypt")
        return encrypt
    return extract_encrypted_xml(body)


def _notification_fields(plain: bytes) -> tuple[str, str]:
    """Return (callback_token, open_kfid) from a decrypted KF notification."""
    text = plain.decode("utf-8", errors="strict")
    token = ""
    open_kfid = ""
    stripped = text.lstrip()
    if stripped[:1] == "{":
        data = json.loads(text)
        token = str(data.get("Token") or data.get("token") or "")
        open_kfid = str(data.get("OpenKfId") or data.get("open_kfid") or "")
    else:
        import xml.etree.ElementTree as ET

        root = ET.fromstring(text)
        token = (root.findtext("Token") or "").strip()
        open_kfid = (root.findtext("OpenKfId") or "").strip()
    if not token or not open_kfid:
        raise WechatProtocolError("微信客服通知缺少 Token 或 OpenKfId")
    return token, open_kfid


class WechatKfAdapter:
    channel = WECHAT_KF
    capabilities = ChannelCapabilities(
        message_types=frozenset({"text", "event"}),
        supports_inbound=True,
        supports_outbound=True,
        supports_streaming=False,
        requires_signature=True,
        requires_encryption=True,
        reply_window_seconds=KF_REPLY_WINDOW_SECONDS,
    )

    def __init__(
        self,
        *,
        channel_instance_id: str,
        corp_id: str,
        token: str,
        encoding_aes_key: str,
        replay_window_seconds: int = DEFAULT_REPLAY_WINDOW_SECONDS,
    ):
        if not isinstance(channel_instance_id, str) or not channel_instance_id.strip():
            raise ValueError("channel_instance_id is required")
        if not isinstance(corp_id, str) or not corp_id.strip():
            raise ValueError("corp_id is required")
        if not isinstance(token, str) or not token.strip():
            raise ValueError("token is required")
        self.channel_instance_id = channel_instance_id.strip()
        self.corp_id = corp_id.strip()
        self.token = token
        self._aes_key = decode_aes_key(encoding_aes_key)
        self.replay_window_seconds = replay_window_seconds

    def verify_echo(
        self, *, msg_signature: str, timestamp: str, nonce: str, echostr: str, now: float | None = None
    ) -> str:
        """Verify the GET handshake and return the decrypted echostr plaintext."""
        current = time.time() if now is None else now
        parsed = check_timestamp(timestamp, now=current, window_seconds=self.replay_window_seconds)
        if not verify_msg_signature(
            token=self.token, timestamp=str(parsed), nonce=nonce, encrypt=echostr, msg_signature=msg_signature
        ):
            raise WechatProtocolError("微信客服回调签名无效")
        try:
            return decrypt_envelope(
                aes_key=self._aes_key, encrypt=echostr, expected_receiver_id=self.corp_id, receiver_label="CorpID"
            ).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WechatProtocolError("echostr解密结果无效") from exc

    def verify_and_extract_notification(
        self, *, body: bytes, msg_signature: str, timestamp: str, nonce: str, now: float | None = None
    ) -> tuple[str, str]:
        """Verify the POST notification and return (callback_token, open_kfid)."""
        current = time.time() if now is None else now
        parsed = check_timestamp(timestamp, now=current, window_seconds=self.replay_window_seconds)
        encrypt = _envelope_encrypt(body)
        if not verify_msg_signature(
            token=self.token, timestamp=str(parsed), nonce=nonce, encrypt=encrypt, msg_signature=msg_signature
        ):
            raise WechatProtocolError("微信客服回调签名无效")
        replay_key = hashlib.sha256(
            f"{self.channel_instance_id}:kf:{parsed}:{nonce}:{msg_signature}".encode()
        ).hexdigest()
        if not replay_guard.check_and_mark(replay_key, now=current, ttl=self.replay_window_seconds):
            raise WechatProtocolError("微信客服回调重复提交")
        plain = decrypt_envelope(
            aes_key=self._aes_key, encrypt=encrypt, expected_receiver_id=self.corp_id, receiver_label="CorpID"
        )
        return _notification_fields(plain)

    def normalize_item(
        self, item: Mapping[str, Any], *, trace_id: str, now: float | None = None
    ) -> WechatKfInboundEnvelope | None:
        """Normalize one sync_msg item; return None for anything but customer text.

        Only ``origin == 3`` (external customer) text is user input. Other
        origins/types (system, servicer, image, voice, events) are skipped —
        the reference implementations that don't do this leak or mis-handle them.
        """
        if not isinstance(item, Mapping):
            return None
        if int(item.get("origin") or 0) != 3 or item.get("msgtype") != "text":
            return None
        msgid = str(item.get("msgid") or "").strip()
        open_kfid = str(item.get("open_kfid") or "").strip()
        external_userid = str(item.get("external_userid") or "").strip()
        content = str(((item.get("text") or {}).get("content")) or "").strip()
        if not msgid or not open_kfid or not external_userid or not content:
            return None
        send_time = int(item.get("send_time") or (time.time() if now is None else now))
        received_at = datetime.fromtimestamp(send_time, tz=timezone.utc).replace(tzinfo=None)
        external_conversation_id = f"{self.channel_instance_id}:{open_kfid}:{external_userid}"
        return WechatKfInboundEnvelope(
            message=InboundMessageInput(
                channel_instance_id=self.channel_instance_id,
                external_message_id=msgid,
                external_conversation_id=external_conversation_id,
                sender_identity_id=external_userid,
                text=content,
                trace_id=trace_id,
                message_type="text",
                payload={
                    "channel": self.channel,
                    "openKfId": open_kfid,
                    "protocol": "wechat.kf.sync_msg.v1",
                },
                reply_window_expires_at=received_at + timedelta(seconds=KF_REPLY_WINDOW_SECONDS),
            ),
            task_payload={"channel": self.channel, "traceId": trace_id, "externalIdentityId": external_userid},
            open_kfid=open_kfid,
            external_userid=external_userid,
        )

    def normalize(self, **kwargs: Any) -> WechatKfInboundEnvelope | None:
        return self.normalize_item(**kwargs)
