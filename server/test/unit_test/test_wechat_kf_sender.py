"""WeChat 客服 reply sender: single text + link card, recipient parsing."""

from __future__ import annotations

import pytest

from integrations.channels.base import DeliveryReceipt
from integrations.channels.wechat_kf.outbound import WechatKfSender


class _FakeKfTransport:
    def __init__(self):
        self.texts = []
        self.links = []

    async def send_text(self, *, open_kfid, external_userid, content):
        self.texts.append({"open_kfid": open_kfid, "external_userid": external_userid, "content": content})
        return DeliveryReceipt(status="delivered", provider_message_id="mid")

    async def send_link(self, *, open_kfid, external_userid, title, desc, url):
        self.links.append({"open_kfid": open_kfid, "external_userid": external_userid, "title": title, "desc": desc, "url": url})
        return DeliveryReceipt(status="delivered")


@pytest.mark.asyncio
async def test_send_text_cleans_markdown_and_targets_kf_and_user():
    transport = _FakeKfTransport()
    sender = WechatKfSender(channel_instance_id="kf-1", transport=transport)
    payload = {"externalConversationId": "kf-1:wkAAA:wmUser", "summary": "**已到港** `BL-1`"}

    receipt = await sender.send(payload=payload)

    assert receipt.status == "delivered"
    assert len(transport.texts) == 1
    sent = transport.texts[0]
    assert sent["open_kfid"] == "wkAAA" and sent["external_userid"] == "wmUser"
    assert "**" not in sent["content"] and "`" not in sent["content"]
    assert "已到港" in sent["content"] and "BL-1" in sent["content"]


@pytest.mark.asyncio
async def test_send_result_card_uses_link_message():
    transport = _FakeKfTransport()
    sender = WechatKfSender(channel_instance_id="kf-1", transport=transport)
    payload = {"externalConversationId": "kf-1:wkAAA:wmUser"}

    receipt = await sender.send_result_card(payload=payload, title="业务查询", description="很长的摘要", url="https://x/#/shared?token=psr_a")

    assert receipt.status == "delivered"
    assert transport.links[0]["url"] == "https://x/#/shared?token=psr_a"
    assert transport.links[0]["external_userid"] == "wmUser"


@pytest.mark.asyncio
async def test_send_fails_closed_without_transport_or_recipient():
    # No transport → uncertain (never claims a delivery that didn't happen).
    sender = WechatKfSender(channel_instance_id="kf-1")
    r = await sender.send(payload={"externalConversationId": "kf-1:wkAAA:wmUser", "summary": "hi"})
    assert r.status == "uncertain" and r.uncertain

    # Malformed conversation id → failed, no send.
    transport = _FakeKfTransport()
    sender2 = WechatKfSender(channel_instance_id="kf-1", transport=transport)
    r2 = await sender2.send(payload={"externalConversationId": "other:x", "summary": "hi"})
    assert r2.status == "failed"
    assert transport.texts == []


@pytest.mark.asyncio
async def test_send_refuses_expired_reply_window():
    transport = _FakeKfTransport()
    sender = WechatKfSender(channel_instance_id="kf-1", transport=transport)
    payload = {
        "externalConversationId": "kf-1:wkAAA:wmUser", "summary": "hi",
        "replyWindowExpiresAt": "2000-01-01T00:00:00+00:00",
    }
    r = await sender.send(payload=payload)
    assert r.status == "failed" and (r.metadata or {}).get("reason") == "reply_window_expired"
    assert transport.texts == []
