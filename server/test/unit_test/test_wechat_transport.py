"""WeChat customer-service send transport: outcome classification.

The distinction that matters is between "nothing was sent" (safe to retry),
"outcome unknown" (must not retry, must not claim success) and "permanently
rejected". Getting it wrong either duplicates a message to a real customer or
reports a delivery that never happened.
"""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from core.delivery import DeliveryRetryableError
from integrations.channels.base import DeliveryReceipt, OutboundMessage
from integrations.channels.wechat_official_account import WechatOfficialAccountSender
from integrations.channels.wechat_transport import (
    WechatAccessTokenCache,
    WechatCustomerServiceTransport,
    WechatSendError,
)


APP_ID = "wx-test-app"
APP_SECRET = "test-secret"
OPEN_ID = "openid_customer"


class _StubTokenCache:
    """Token cache that never touches the network."""

    def __init__(self, *, token: str = "token-1"):
        self.token_value = token
        self.invalidated = 0
        self.fetches = 0

    async def token(self, *, app_id, app_secret, now=None):
        self.fetches += 1
        return self.token_value

    def invalidate(self, app_id):
        self.invalidated += 1
        self.token_value = f"{self.token_value}-refreshed"


def _transport(cache=None):
    return WechatCustomerServiceTransport(
        app_id=APP_ID,
        app_secret=APP_SECRET,
        token_cache=cache if cache is not None else _StubTokenCache(),
    )


def test_transport_requires_app_credentials():
    with pytest.raises(WechatSendError):
        WechatCustomerServiceTransport(app_id="", app_secret=APP_SECRET)
    with pytest.raises(WechatSendError):
        WechatCustomerServiceTransport(app_id=APP_ID, app_secret="  ")


def test_empty_or_oversized_content_is_handled_before_sending():
    with pytest.raises(WechatSendError):
        WechatCustomerServiceTransport._text_body("   ")
    body = WechatCustomerServiceTransport._text_body("x" * 5000)
    # Truncated instead of letting the provider reject the whole reply.
    assert len(body["text"]["content"]) <= 2000
    assert body["text"]["content"].endswith("（详见官网）")


def test_invalid_recipient_is_rejected_before_sending():
    with pytest.raises(WechatSendError):
        WechatCustomerServiceTransport._recipient("")
    with pytest.raises(WechatSendError):
        WechatCustomerServiceTransport._recipient("x" * 200)


def test_success_is_reported_as_delivered():
    receipt, stale = WechatCustomerServiceTransport._classify({"errcode": 0, "msgid": "9001"})
    assert stale is False
    assert receipt.status == "delivered"
    assert receipt.uncertain is False
    assert receipt.provider_message_id == "9001"


@pytest.mark.parametrize("code", [45015, 48001, 48002, 40003])
def test_permanent_provider_errors_are_rejected_not_retried(code):
    receipt, stale = WechatCustomerServiceTransport._classify({"errcode": code, "errmsg": "nope"})
    assert stale is False
    assert receipt.status == "failed"
    assert receipt.uncertain is False
    assert str(code) in (receipt.metadata or {})["reason"]


@pytest.mark.parametrize("code", [-1, 45009, 45011, 48004])
def test_transient_provider_errors_raise_retryable(code):
    with pytest.raises(DeliveryRetryableError):
        WechatCustomerServiceTransport._classify({"errcode": code})


def test_token_errors_ask_for_one_refresh():
    receipt, stale = WechatCustomerServiceTransport._classify({"errcode": 40001})
    assert stale is True
    assert receipt.status == "failed"


def test_unmapped_error_code_is_permanent_so_the_queue_does_not_spin():
    receipt, stale = WechatCustomerServiceTransport._classify({"errcode": 987654})
    assert stale is False
    assert receipt.status == "failed"
    assert (receipt.metadata or {})["reason"] == "wechat_send_error_987654"


def test_unreadable_error_code_is_uncertain():
    receipt, stale = WechatCustomerServiceTransport._classify({"errcode": "not-a-number"})
    assert stale is False
    assert receipt.status == "uncertain"
    assert receipt.uncertain is True


class _FakeResponse:
    def __init__(self, *, status=200, body=None, error=None):
        self.status = status
        self._body = body if body is not None else {}
        self._error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def json(self, content_type=None):
        if self._error is not None:
            raise self._error
        return self._body


class _FakeSession:
    """Minimal aiohttp.ClientSession stand-in for one POST."""

    def __init__(self, *, response=None, post_error=None):
        self._response = response
        self._post_error = post_error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    def post(self, _url, **_kwargs):
        if self._post_error is not None:
            raise self._post_error
        return self._response


def _patch_session(monkeypatch, session):
    import integrations.channels.wechat_transport as module

    monkeypatch.setattr(module.aiohttp, "ClientSession", lambda **_kwargs: session)


@pytest.mark.asyncio
async def test_connection_failure_before_sending_is_retryable(monkeypatch):
    """Nothing left the process, so a retry cannot duplicate the message."""
    transport = _transport()
    _patch_session(
        monkeypatch,
        _FakeSession(post_error=aiohttp.ClientConnectorError(connection_key=None, os_error=OSError("refused"))),
    )
    with pytest.raises(DeliveryRetryableError, match="wechat_send_unreachable"):
        await transport.send_text(open_id=OPEN_ID, content="result")


@pytest.mark.asyncio
async def test_timeout_after_the_request_was_written_is_uncertain(monkeypatch):
    """The customer may already have the message, so never retry or claim success."""
    transport = _transport()
    _patch_session(monkeypatch, _FakeSession(response=_FakeResponse(error=TimeoutError("read timeout"))))
    receipt = await transport.send_text(open_id=OPEN_ID, content="result")
    assert receipt.status == "uncertain"
    assert receipt.uncertain is True
    assert (receipt.metadata or {})["reason"] == "wechat_send_result_unknown"


@pytest.mark.asyncio
async def test_provider_5xx_is_retryable(monkeypatch):
    transport = _transport()
    _patch_session(monkeypatch, _FakeSession(response=_FakeResponse(status=503, body={})))
    with pytest.raises(DeliveryRetryableError, match="wechat_send_upstream_error"):
        await transport.send_text(open_id=OPEN_ID, content="result")


@pytest.mark.asyncio
async def test_successful_provider_response_is_delivered(monkeypatch):
    transport = _transport()
    _patch_session(monkeypatch, _FakeSession(response=_FakeResponse(body={"errcode": 0, "msgid": "77"})))
    receipt = await transport.send_text(open_id=OPEN_ID, content="result")
    assert receipt.status == "delivered"
    assert receipt.provider_message_id == "77"


@pytest.mark.asyncio
async def test_stale_token_is_refreshed_once_then_gives_up():
    cache = _StubTokenCache()
    transport = _transport(cache)
    attempts = []

    async def always_stale(*, token, payload):
        attempts.append(token)
        return DeliveryReceipt(status="failed", metadata={"reason": "wechat_token_stale"}), True

    transport._post = always_stale
    with pytest.raises(DeliveryRetryableError, match="wechat_token_stale"):
        await transport.send_text(open_id=OPEN_ID, content="result")
    # Exactly two attempts: the original and one after invalidating the token.
    assert len(attempts) == 2
    # Both rejections drop the cached token: a token WeChat just called invalid
    # must not stay cached for the next task.
    assert cache.invalidated == 2


@pytest.mark.asyncio
async def test_send_returns_the_first_definitive_receipt():
    cache = _StubTokenCache()
    transport = _transport(cache)
    seen = {}

    async def ok(*, token, payload):
        seen["token"] = token
        seen["payload"] = payload
        return DeliveryReceipt(status="delivered", provider_message_id="42"), False

    transport._post = ok
    receipt = await transport.send_text(open_id=OPEN_ID, content="  BL-001 已到港  ")

    assert receipt.status == "delivered"
    assert seen["payload"]["touser"] == OPEN_ID
    assert seen["payload"]["msgtype"] == "text"
    assert seen["payload"]["text"]["content"] == "BL-001 已到港"
    assert cache.invalidated == 0


@pytest.mark.asyncio
async def test_token_cache_reuses_a_live_token_and_refreshes_after_expiry():
    cache = WechatAccessTokenCache()
    fetched = []

    async def fake_fetch(*, app_id, app_secret):
        fetched.append(app_id)
        return f"token-{len(fetched)}", 7200

    cache._fetch = fake_fetch
    first = await cache.token(app_id=APP_ID, app_secret=APP_SECRET, now=1_000.0)
    second = await cache.token(app_id=APP_ID, app_secret=APP_SECRET, now=1_100.0)
    assert first == second == "token-1"
    assert len(fetched) == 1

    # 7200s lifetime minus the 300s safety margin.
    third = await cache.token(app_id=APP_ID, app_secret=APP_SECRET, now=1_000.0 + 6_901)
    assert third == "token-2"
    assert len(fetched) == 2


@pytest.mark.asyncio
async def test_concurrent_refresh_fetches_only_once():
    cache = WechatAccessTokenCache()
    calls = []

    async def slow_fetch(*, app_id, app_secret):
        calls.append(app_id)
        await asyncio.sleep(0.01)
        return "token-shared", 7200

    cache._fetch = slow_fetch
    tokens = await asyncio.gather(*[
        cache.token(app_id=APP_ID, app_secret=APP_SECRET, now=500.0) for _ in range(5)
    ])
    assert tokens == ["token-shared"] * 5
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_sender_without_transport_stays_uncertain():
    sender = WechatOfficialAccountSender(channel_instance_id="oa-1")
    receipt = await sender.send(payload={
        "externalConversationId": "oa-1:openid_a",
        "summary": "结果",
    })
    assert receipt.status == "uncertain"
    assert (receipt.metadata or {})["reason"] == "provider_transport_not_configured"


@pytest.mark.asyncio
async def test_sender_recovers_the_openid_from_the_conversation_key():
    class _Transport:
        def __init__(self):
            self.calls = []

        async def send_text(self, *, open_id, content):
            self.calls.append((open_id, content))
            return DeliveryReceipt(status="delivered")

    transport = _Transport()
    sender = WechatOfficialAccountSender(channel_instance_id="oa-1", transport=transport)
    receipt = await sender.send(payload={
        "externalConversationId": "oa-1:openid_b",
        "summary": "已核实",
    })
    assert receipt.status == "delivered"
    assert transport.calls == [("openid_b", "已核实")]


@pytest.mark.asyncio
async def test_sender_refuses_a_conversation_key_from_another_instance():
    class _Transport:
        async def send_text(self, *, open_id, content):  # pragma: no cover - must not run
            raise AssertionError("must not send to a foreign channel instance")

    sender = WechatOfficialAccountSender(channel_instance_id="oa-1", transport=_Transport())
    receipt = await sender.send(payload={
        "externalConversationId": "oa-other:openid_c",
        "summary": "结果",
    })
    assert receipt.status == "failed"
    assert (receipt.metadata or {})["reason"] == "missing_recipient_identity"


@pytest.mark.asyncio
async def test_sender_checks_the_reply_window_before_calling_the_provider():
    class _Transport:
        async def send_text(self, *, open_id, content):  # pragma: no cover - must not run
            raise AssertionError("must not send outside the reply window")

    sender = WechatOfficialAccountSender(channel_instance_id="oa-1", transport=_Transport())
    receipt = await sender.send(
        message=OutboundMessage(
            channel="wechat_official_account",
            channel_instance_id="oa-1",
            external_conversation_id="oa-1:openid_d",
            text="结果",
            idempotency_key="k",
            trace_id="t",
            metadata={"replyWindowExpiresAt": "2000-01-01T00:00:00+00:00"},
        )
    )
    assert receipt.status == "failed"
    assert (receipt.metadata or {})["reason"] == "reply_window_expired"
