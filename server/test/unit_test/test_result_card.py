"""The closing result card is a long-answer overflow affordance with a no-login link."""

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


def _dead_sessionmaker():
    def _factory():
        raise AssertionError("sessionmaker must not be called when no token is minted")

    return _factory


@pytest.mark.asyncio
async def test_card_skipped_when_no_share_url():
    sender = _CardSender()
    payload = {"title": "业务查询", "summary": "已到港，可安排提货。"}

    result = await platform_worker._send_result_card(sender, payload=payload, share_url=None)

    assert result == "skipped"
    assert sender.cards == []


@pytest.mark.asyncio
async def test_card_sent_with_share_url():
    sender = _CardSender()
    payload = {"title": "业务查询", "summary": "详情很多……"}

    result = await platform_worker._send_result_card(
        sender, payload=payload, share_url="https://adp.example.com/#/shared?token=psr_abc"
    )

    assert result == "delivered"
    assert len(sender.cards) == 1
    assert sender.cards[0]["url"] == "https://adp.example.com/#/shared?token=psr_abc"


@pytest.mark.asyncio
async def test_mint_share_url_none_for_short_answer(monkeypatch):
    monkeypatch.setattr(
        platform_worker.tagentic_config, "PLATFORM_PUBLIC_BASE_URL", "https://adp.example.com", raising=False
    )
    payload = {"executionRunId": "run-1", "accountId": "acc-1", "summary": "已到港。"}

    url = await platform_worker._mint_share_url(_dead_sessionmaker(), payload)

    assert url is None


@pytest.mark.asyncio
async def test_mint_share_url_none_without_public_base_url(monkeypatch):
    monkeypatch.setattr(platform_worker.tagentic_config, "PLATFORM_PUBLIC_BASE_URL", "", raising=False)
    long_summary = "x" * (platform_worker.RESULT_CARD_MIN_CHARS + 50)
    payload = {"executionRunId": "run-1", "accountId": "acc-1", "summary": long_summary}

    url = await platform_worker._mint_share_url(_dead_sessionmaker(), payload)

    assert url is None


@pytest.mark.asyncio
async def test_mint_share_url_none_without_execution_run(monkeypatch):
    monkeypatch.setattr(
        platform_worker.tagentic_config, "PLATFORM_PUBLIC_BASE_URL", "https://adp.example.com", raising=False
    )
    long_summary = "x" * (platform_worker.RESULT_CARD_MIN_CHARS + 50)
    payload = {"accountId": "acc-1", "summary": long_summary}  # no executionRunId

    url = await platform_worker._mint_share_url(_dead_sessionmaker(), payload)

    assert url is None
