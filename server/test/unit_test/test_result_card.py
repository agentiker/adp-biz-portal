"""The closing result card is an overflow affordance, not a per-reply decoration."""

from __future__ import annotations

import pytest

from core import platform_worker
from integrations.channels.base import DeliveryReceipt


class _CardSender:
    def __init__(self):
        self.cards = []

    async def send_result_card(self, *, payload, title, description, url):
        self.cards.append({"title": title, "description": description, "url": url})
        return DeliveryReceipt(status="delivered")


@pytest.mark.asyncio
async def test_short_answer_gets_no_card(monkeypatch):
    monkeypatch.setattr(
        platform_worker.tagentic_config, "PLATFORM_PUBLIC_BASE_URL", "https://adp.example.com", raising=False
    )
    sender = _CardSender()
    payload = {"conversationId": "c1", "title": "业务查询", "summary": "已到港，可安排提货。"}

    result = await platform_worker._send_result_card(sender, payload=payload)

    assert result == "skipped_short_answer"
    assert sender.cards == []


@pytest.mark.asyncio
async def test_long_answer_gets_a_card(monkeypatch):
    monkeypatch.setattr(
        platform_worker.tagentic_config, "PLATFORM_PUBLIC_BASE_URL", "https://adp.example.com", raising=False
    )
    sender = _CardSender()
    long_summary = "详情如下：" + "该提单包含多段运输与多条状态记录。" * 60
    assert len(long_summary) > platform_worker.RESULT_CARD_MIN_CHARS
    payload = {"conversationId": "c1", "title": "业务查询", "summary": long_summary}

    result = await platform_worker._send_result_card(sender, payload=payload)

    assert result == "delivered"
    assert len(sender.cards) == 1
    assert sender.cards[0]["url"].startswith("https://adp.example.com")


@pytest.mark.asyncio
async def test_no_card_without_a_public_url(monkeypatch):
    monkeypatch.setattr(platform_worker.tagentic_config, "PLATFORM_PUBLIC_BASE_URL", "", raising=False)
    sender = _CardSender()
    long_summary = "x" * (platform_worker.RESULT_CARD_MIN_CHARS + 50)
    payload = {"conversationId": "c1", "title": "业务查询", "summary": long_summary}

    result = await platform_worker._send_result_card(sender, payload=payload)

    assert result == "skipped_no_public_url"
    assert sender.cards == []
