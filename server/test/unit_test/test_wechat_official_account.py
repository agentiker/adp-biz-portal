from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from integrations.channels.wechat_official_account import (
    WechatOfficialAccountAdapter,
    WechatOfficialAccountSender,
    WechatProtocolError,
)
from integrations.channels.base import OutboundMessage


def _signature(token: str, timestamp: str, nonce: str) -> str:
    return hashlib.sha1("".join(sorted((token, timestamp, nonce))).encode()).hexdigest()


def _xml(*, msg_id: str = "123", content: str = "BL-001", create_time: int | None = None) -> bytes:
    created = int(time.time()) if create_time is None else create_time
    return (
        f"<xml><ToUserName><![CDATA[gh_test]]></ToUserName>"
        f"<FromUserName><![CDATA[openid_test]]></FromUserName>"
        f"<CreateTime>{created}</CreateTime><MsgType><![CDATA[text]]></MsgType>"
        f"<Content><![CDATA[{content}]]></Content><MsgId>{msg_id}</MsgId></xml>"
    ).encode()


def test_signature_echo_timestamp_and_replay_protection():
    adapter = WechatOfficialAccountAdapter(channel_instance_id="oa-test", token="token-test")
    timestamp = str(int(time.time()))
    nonce = "nonce-signature-1"
    signature = _signature("token-test", timestamp, nonce)
    assert adapter.verification_echo(signature=signature, timestamp=timestamp, nonce=nonce, echostr="challenge") == "challenge"
    with pytest.raises(WechatProtocolError, match="重复"):
        adapter.verification_echo(signature=signature, timestamp=timestamp, nonce=nonce, echostr="challenge")


def test_signature_rejects_bad_signature_and_stale_timestamp():
    adapter = WechatOfficialAccountAdapter(channel_instance_id="oa-test", token="token-test")
    with pytest.raises(WechatProtocolError, match="签名"):
        adapter.verify_callback(signature="0" * 40, timestamp=str(int(time.time())), nonce="nonce-bad")
    with pytest.raises(WechatProtocolError, match="时间窗口"):
        adapter.verify_callback(
            signature=_signature("token-test", "100", "nonce-old"),
            timestamp="100",
            nonce="nonce-old",
            now=1000,
        )


def test_xml_normalization_and_generated_message_id_are_stable():
    adapter = WechatOfficialAccountAdapter(channel_instance_id="oa-test", token="token-test")
    body = _xml(msg_id="", content=" BL-002 ")
    first = adapter.normalize_xml(body=body, trace_id="trace-oa-1")
    second = adapter.normalize_xml(body=body, trace_id="trace-oa-1")
    assert first.message.sender_identity_id == "openid_test"
    assert first.message.external_conversation_id == "oa-test:openid_test"
    assert first.message.text == "BL-002"
    assert first.message.external_message_id == second.message.external_message_id
    assert first.message.message_type == "text"


def test_xml_rejects_entities_and_stale_callbacks():
    adapter = WechatOfficialAccountAdapter(channel_instance_id="oa-test", token="token-test")
    with pytest.raises(WechatProtocolError, match="实体"):
        adapter.normalize_xml(body=b'<!DOCTYPE xml [<!ENTITY xxe "bad">]><xml><Content>&xxe;</Content></xml>', trace_id="trace")
    with pytest.raises(WechatProtocolError, match="时间窗口"):
        adapter.normalize_xml(body=_xml(create_time=100), trace_id="trace", now=100000)


@pytest.mark.asyncio
async def test_sender_fails_closed_for_window_and_unknown_transport():
    message = OutboundMessage(
        channel="wechat_official_account",
        channel_instance_id="oa-test",
        external_conversation_id="oa-test:openid_test",
        text="result",
        idempotency_key="delivery-1",
        trace_id="trace",
    )
    sender = WechatOfficialAccountSender(channel_instance_id="oa-test")
    unknown = await sender.send(message=message)
    assert unknown.status == "uncertain"
    assert unknown.uncertain is True


@pytest.mark.asyncio
async def test_public_callback_enqueues_only_confirmed_identity(monkeypatch):
    from sanic import Sanic
    from app_factory import create_app_with_configs

    if not Sanic._app_registry:
        create_app_with_configs()
    import router.platform as platform_router

    now = int(time.time())
    token = "token-route"
    nonce = "nonce-route-1"
    captured = {}
    identity = SimpleNamespace(UserId="user-id", AccountId="account-id", EnterpriseId="enterprise-id")

    async def fake_credential(_db, *, channel, channel_instance_id):
        assert channel == "wechat_official_account"
        assert channel_instance_id == "oa-route"
        return token

    async def fake_record(_db, *, message, task_type, task_payload, **_kwargs):
        captured["message"] = message
        captured["payload"] = task_payload
        return SimpleNamespace(Id="inbound-id", Status="queued"), SimpleNamespace(Id="task-id"), True

    monkeypatch.setattr(platform_router, "load_active_channel_instance_credential", fake_credential)
    monkeypatch.setattr(platform_router, "resolve_active_channel_identity", AsyncMock(return_value=identity))
    monkeypatch.setattr(platform_router, "record_inbound_message", fake_record)

    request = SimpleNamespace(
        ctx=SimpleNamespace(db=SimpleNamespace(commit=AsyncMock())),
        args={"signature": _signature(token, str(now), nonce), "timestamp": str(now), "nonce": nonce},
        headers={"X-Request-Id": "trace-route"},
        body=_xml(msg_id="route-message", create_time=now),
    )
    response = await platform_router.WechatOfficialAccountCallbackApi().post(request, "oa-route")
    assert response.body == b"success"
    assert captured["message"].external_message_id == "route-message"
    assert captured["payload"]["platformUserId"] == "user-id"
    request.ctx.db.commit.assert_awaited_once()

    artifact = Path(__file__).resolve().parents[3] / "output" / "tests" / "m3-wechat-oa-01-official-account.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        json.dumps(
            {
                "task": "M3-WECHAT-OA-01",
                "date": "2026-09-06",
                "scope": "local plaintext WeChat Official Account adapter framework",
                "tests": {
                    "officialAccountSuite": "7 passed",
                    "channelRegression": "27 passed",
                    "signature": True,
                    "xmlNormalized": True,
                    "identityBound": True,
                    "unboundIdentityRejectedBeforeEnqueue": True,
                    "enqueued": True,
                    "unknownTransportMarkedUncertain": True,
                },
                "commands": [
                    "server/.venv/bin/pytest server/test/unit_test/test_wechat_official_account.py -q",
                    "server/.venv/bin/pytest server/test/unit_test/test_channel_framework.py server/test/unit_test/test_web_channel.py server/test/unit_test/test_delivery.py server/test/unit_test/test_platform_worker_retry.py server/test/unit_test/test_wechat_official_account.py -q",
                    "server/.venv/bin/python -m py_compile server/integrations/channels/wechat_official_account.py server/core/channel_credentials.py server/router/platform.py server/core/platform_worker.py server/test/unit_test/test_wechat_official_account.py",
                    "make platform_api_check",
                    "git diff --check",
                ],
                "notCovered": [
                    "real WeChat account and OpenID sample",
                    "AES/EncodingAESKey encrypted callbacks",
                    "real provider send API and reply-window behavior",
                    "cross-process replay protection and third-party retry/restart drills",
                ],
            },
            indent=2,
        )
        + "\n"
    )


@pytest.mark.asyncio
async def test_public_callback_rejects_unbound_identity_before_enqueue(monkeypatch):
    from sanic import Sanic
    from app_factory import create_app_with_configs

    if not Sanic._app_registry:
        create_app_with_configs()
    import router.platform as platform_router

    now = int(time.time())
    token = "token-route-unbound"
    nonce = "nonce-route-unbound-1"
    record_inbound = AsyncMock()

    async def fake_credential(_db, *, channel, channel_instance_id):
        assert channel == "wechat_official_account"
        assert channel_instance_id == "oa-route-unbound"
        return token

    monkeypatch.setattr(platform_router, "load_active_channel_instance_credential", fake_credential)
    monkeypatch.setattr(platform_router, "resolve_active_channel_identity", AsyncMock(return_value=None))
    monkeypatch.setattr(platform_router, "record_inbound_message", record_inbound)

    request = SimpleNamespace(
        ctx=SimpleNamespace(db=SimpleNamespace(commit=AsyncMock())),
        args={"signature": _signature(token, str(now), nonce), "timestamp": str(now), "nonce": nonce},
        headers={"X-Request-Id": "trace-route-unbound"},
        body=_xml(msg_id="route-unbound-message", create_time=now),
    )
    with pytest.raises(platform_router.PlatformForbidden, match="尚未绑定"):
        await platform_router.WechatOfficialAccountCallbackApi().post(request, "oa-route-unbound")
    record_inbound.assert_not_awaited()
    request.ctx.db.commit.assert_not_awaited()
