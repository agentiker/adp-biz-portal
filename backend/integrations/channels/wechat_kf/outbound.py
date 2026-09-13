"""WeChat 客服 reply sender: one complete answer, plus a link card when long.

kf has no ``news`` message type, so the closing card is a ``link`` message.
Mirrors the official-account sender contract (send + send_result_card) so the
worker's single-answer + card reply path works unchanged; ``supports_incremental_stream``
is intentionally absent — 客服 replies are discrete.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from integrations.channels.base import DeliveryReceipt
from integrations.channels.text_format import to_plain_text
from integrations.channels.wechat_kf.adapter import WECHAT_KF
from integrations.channels.wechat_transport import WechatSendError


class WechatKfSender:
    channel = WECHAT_KF

    def __init__(self, *, channel_instance_id: str, transport: Any = None):
        self.channel_instance_id = channel_instance_id
        self._transport = transport

    async def send(
        self, *, message: Any = None, payload: Mapping[str, Any] | None = None
    ) -> DeliveryReceipt:
        payload = dict(payload or {})
        if _reply_window_expired(payload.get("replyWindowExpiresAt")):
            return DeliveryReceipt(status="failed", uncertain=False, metadata={"reason": "reply_window_expired"})
        if self._transport is None:
            return DeliveryReceipt(status="uncertain", uncertain=True, metadata={"reason": "provider_transport_not_configured"})
        recipient = self._recipient(payload)
        if recipient is None:
            return DeliveryReceipt(status="failed", uncertain=False, metadata={"reason": "missing_recipient_identity"})
        open_kfid, external_userid = recipient
        content = to_plain_text(str(payload.get("summary") or "")) or str(payload.get("summary") or "")
        try:
            return await self._transport.send_text(
                open_kfid=open_kfid, external_userid=external_userid, content=content
            )
        except WechatSendError as exc:
            return DeliveryReceipt(status="failed", uncertain=False, metadata={"reason": str(exc)})

    async def send_result_card(self, *, payload: Mapping[str, Any], title: str, description: str, url: str) -> DeliveryReceipt:
        if self._transport is None:
            return DeliveryReceipt(status="uncertain", uncertain=True, metadata={"reason": "provider_transport_not_configured"})
        recipient = self._recipient(dict(payload))
        if recipient is None:
            return DeliveryReceipt(status="failed", uncertain=False, metadata={"reason": "missing_recipient_identity"})
        open_kfid, external_userid = recipient
        return await self._transport.send_link(
            open_kfid=open_kfid, external_userid=external_userid, title=title, desc=description, url=url
        )

    def _recipient(self, payload: Mapping[str, Any]) -> tuple[str, str] | None:
        """Recover (open_kfid, external_userid) from ``<instance>:<kf>:<user>``.

        The recipient never comes from anywhere the browser or model could
        influence — only from the conversation id produced by normalize_item.
        """
        conversation = str(payload.get("externalConversationId") or "")
        prefix = f"{self.channel_instance_id}:"
        if not conversation.startswith(prefix):
            return None
        rest = conversation[len(prefix):]
        open_kfid, _, external_userid = rest.partition(":")
        open_kfid = open_kfid.strip()
        external_userid = external_userid.strip()
        if not open_kfid or not external_userid:
            return None
        return open_kfid, external_userid


def _reply_window_expired(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        expires = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return True
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires <= datetime.now(timezone.utc)
