from __future__ import annotations

import hashlib
import hmac
import base64
import json
import struct
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from integrations.channels.wechat_official_account import (
    WechatOfficialAccountAdapter,
    WechatOfficialAccountSender,
    WechatProtocolError,
)
from integrations.channels.base import OutboundMessage


def _stub_callback_side_effects(monkeypatch, platform_router, *, claimed=None):
    """Neutralize durable side effects the route performs around verification."""
    claims = claimed if claimed is not None else []

    async def fake_claim(_db, *, channel, channel_instance_id, replay_key, ttl_seconds):
        claims.append((channel, channel_instance_id, replay_key, ttl_seconds))

    monkeypatch.setattr(platform_router, "claim_replay_key", fake_claim)
    monkeypatch.setattr(platform_router, "prune_expired_replay_markers", AsyncMock(return_value=0))
    monkeypatch.setattr(platform_router, "create_audit", AsyncMock())
    return claims


def _signature(token: str, timestamp: str, nonce: str) -> str:
    return hashlib.sha1("".join(sorted((token, timestamp, nonce))).encode()).hexdigest()


def _encrypted_payload(*, xml: bytes, app_id: str, key: bytes) -> str:
    payload = b"r" * 16 + struct.pack("!I", len(xml)) + xml + app_id.encode()
    padding = 32 - (len(payload) % 32)
    payload += bytes([padding]) * padding
    encryptor = Cipher(algorithms.AES(key), modes.CBC(key[:16])).encryptor()
    return base64.b64encode(encryptor.update(payload) + encryptor.finalize()).decode()


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


def test_aes_callback_verifies_decrypts_and_rejects_wrong_app_id():
    key = b"0123456789abcdef0123456789abcdef"
    aes_key = base64.b64encode(key).decode().rstrip("=")
    adapter = WechatOfficialAccountAdapter(
        channel_instance_id="oa-aes",
        token="token-aes",
        app_id="wx-test-app",
        encoding_aes_key=aes_key,
    )
    timestamp = str(int(time.time()))
    nonce = "nonce-aes-1"
    body = _xml(msg_id="aes-message")
    encrypted = _encrypted_payload(xml=body, app_id="wx-test-app", key=key)
    msg_signature = hashlib.sha1("".join(sorted(("token-aes", timestamp, nonce, encrypted))).encode()).hexdigest()
    adapter.verify_encrypted_callback(msg_signature=msg_signature, timestamp=timestamp, nonce=nonce, encrypt=encrypted)
    assert adapter.decrypt_xml(encrypted) == body
    with pytest.raises(WechatProtocolError, match="签名"):
        adapter.verify_encrypted_callback(msg_signature="0" * 40, timestamp=timestamp, nonce="nonce-aes-bad", encrypt=encrypted)
    with pytest.raises(WechatProtocolError, match="解密"):
        adapter.decrypt_xml(base64.b64encode(b"short").decode())
    with pytest.raises(WechatProtocolError, match="重复"):
        adapter.verify_encrypted_callback(msg_signature=msg_signature, timestamp=timestamp, nonce=nonce, encrypt=encrypted)

    wrong_app = _encrypted_payload(xml=_xml(msg_id="wrong-app"), app_id="wx-other", key=key)
    with pytest.raises(WechatProtocolError, match="AppID"):
        adapter.decrypt_xml(wrong_app)


def test_aes_verification_echo_returns_decrypted_challenge():
    key = b"abcdef0123456789abcdef0123456789"
    aes_key = base64.b64encode(key).decode().rstrip("=")
    adapter = WechatOfficialAccountAdapter(
        channel_instance_id="oa-aes-echo",
        token="token-aes-echo",
        app_id="wx-echo",
        encoding_aes_key=aes_key,
    )
    timestamp = str(int(time.time()))
    nonce = "nonce-aes-echo"
    encrypted = _encrypted_payload(xml=b"challenge", app_id="wx-echo", key=key)
    signature = hashlib.sha1("".join(sorted(("token-aes-echo", timestamp, nonce, encrypted))).encode()).hexdigest()
    assert adapter.verification_echo(
        signature="",
        msg_signature=signature,
        timestamp=timestamp,
        nonce=nonce,
        echostr=encrypted,
        encrypted=True,
    ) == "challenge"


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
    from test.app_bootstrap import ensure_app

    ensure_app()
    import router.platform as platform_router

    now = int(time.time())
    token = "token-route"
    nonce = "nonce-route-1"
    captured = {}
    identity = SimpleNamespace(UserId="user-id", AccountId="account-id", EnterpriseId=None)

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
    claims = _stub_callback_side_effects(monkeypatch, platform_router)

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
    assert captured["payload"]["enterpriseId"] is None
    # The reply deadline travels with the envelope so the sender can refuse a
    # reply the channel would no longer accept.
    assert captured["message"].reply_window_expires_at is not None
    assert len(claims) == 1 and claims[0][0] == "wechat_official_account"
    request.ctx.db.commit.assert_awaited_once()

    artifact = Path(__file__).resolve().parents[3] / "output" / "tests" / "m3-wechat-oa-01-official-account.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        json.dumps(
            {
                "task": "M3-WECHAT-OA-01",
                "date": "2026-09-06",
                "scope": "local plaintext and AES WeChat Official Account adapter framework",
                "tests": {
                    "officialAccountSuite": "10 passed",
                    "channelRegression": "30 passed",
                    "signature": True,
                    "xmlNormalized": True,
                    "identityBound": True,
                    "enterpriseScopeDeferredToWorker": True,
                    "unboundIdentityRejectedBeforeEnqueue": True,
                    "enqueued": True,
                    "unknownTransportMarkedUncertain": True,
                    "aesCallbackVerifiedAndDecrypted": True,
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
                    "real provider send API and reply-window behavior",
                    "cross-process replay protection and third-party retry/restart drills",
                ],
            },
            indent=2,
        )
        + "\n"
    )


@pytest.mark.asyncio
async def test_public_callback_accepts_encrypted_xml(monkeypatch):
    from test.app_bootstrap import ensure_app

    ensure_app()
    import router.platform as platform_router

    now = int(time.time())
    token = "token-route-aes"
    app_id = "wx-route-aes"
    key = b"route-aes-key-012345678901234567"
    aes_key = base64.b64encode(key).decode().rstrip("=")
    nonce = "nonce-route-aes-1"
    message_body = _xml(msg_id="route-aes-message", create_time=now)
    encrypted = _encrypted_payload(xml=message_body, app_id=app_id, key=key)
    msg_signature = hashlib.sha1("".join(sorted((token, str(now), nonce, encrypted))).encode()).hexdigest()
    captured = {}
    identity = SimpleNamespace(UserId="user-aes", AccountId="account-aes", EnterpriseId=None)

    async def fake_credential(_db, *, channel, channel_instance_id):
        assert channel == "wechat_official_account"
        assert channel_instance_id == "oa-route-aes"
        return json.dumps({"token": token, "appId": app_id, "encodingAesKey": aes_key})

    async def fake_record(_db, *, message, task_type, task_payload, **_kwargs):
        captured["message"] = message
        captured["payload"] = task_payload
        return SimpleNamespace(Id="inbound-aes", Status="queued"), SimpleNamespace(Id="task-aes"), True

    monkeypatch.setattr(platform_router, "load_active_channel_instance_credential", fake_credential)
    monkeypatch.setattr(platform_router, "resolve_active_channel_identity", AsyncMock(return_value=identity))
    monkeypatch.setattr(platform_router, "record_inbound_message", fake_record)
    _stub_callback_side_effects(monkeypatch, platform_router)
    request = SimpleNamespace(
        ctx=SimpleNamespace(db=SimpleNamespace(commit=AsyncMock())),
        args={"msg_signature": msg_signature, "timestamp": str(now), "nonce": nonce, "encrypt_type": "aes"},
        headers={"X-Request-Id": "trace-route-aes"},
        body=(f"<xml><Encrypt><![CDATA[{encrypted}]]></Encrypt></xml>").encode(),
    )
    response = await platform_router.WechatOfficialAccountCallbackApi().post(request, "oa-route-aes")
    assert response.body == b"success"
    assert captured["message"].external_message_id == "route-aes-message"
    assert captured["payload"]["enterpriseId"] is None
    request.ctx.db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_public_callback_rejects_unbound_identity_before_enqueue(monkeypatch):
    from test.app_bootstrap import ensure_app

    ensure_app()
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
    _stub_callback_side_effects(monkeypatch, platform_router)

    request = SimpleNamespace(
        ctx=SimpleNamespace(db=SimpleNamespace(commit=AsyncMock())),
        args={"signature": _signature(token, str(now), nonce), "timestamp": str(now), "nonce": nonce},
        headers={"X-Request-Id": "trace-route-unbound"},
        body=_xml(msg_id="route-unbound-message", create_time=now),
    )
    response = await platform_router.WechatOfficialAccountCallbackApi().post(request, "oa-route-unbound")
    # WeChat retries a non-2xx callback and then shows the sender a service
    # failure, so an unbound sender is answered with guidance instead.
    assert response.status == 200
    body = response.body.decode()
    assert "<ToUserName><![CDATA[openid_test]]></ToUserName>" in body
    assert "<FromUserName><![CDATA[gh_test]]></FromUserName>" in body
    assert "绑定" in body
    record_inbound.assert_not_awaited()


@pytest.mark.asyncio
async def test_binding_code_is_confirmed_and_never_reaches_the_agent(monkeypatch):
    """A binding code must be consumed by the identity flow, not forwarded."""
    from test.app_bootstrap import ensure_app

    ensure_app()
    import router.platform as platform_router

    now = int(time.time())
    token = "token-route-bind"
    nonce = "nonce-route-bind-1"
    state = "pci_" + "b" * 43
    record_inbound = AsyncMock()
    confirmed = SimpleNamespace(
        Id="identity-id",
        AccountId="account-bind",
        Channel="wechat_official_account",
        ChannelInstanceId="oa-route-bind",
        ExternalIdentityId="openid_test",
    )
    confirm = AsyncMock(return_value=confirmed)

    async def fake_credential(_db, *, channel, channel_instance_id):
        return token

    monkeypatch.setattr(platform_router, "load_active_channel_instance_credential", fake_credential)
    monkeypatch.setattr(platform_router, "record_inbound_message", record_inbound)
    monkeypatch.setattr(platform_router, "confirm_channel_identity_binding", confirm)
    monkeypatch.setattr(platform_router, "resolve_active_channel_identity", AsyncMock(return_value=None))
    _stub_callback_side_effects(monkeypatch, platform_router)

    request = SimpleNamespace(
        ctx=SimpleNamespace(db=SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())),
        args={"signature": _signature(token, str(now), nonce), "timestamp": str(now), "nonce": nonce},
        headers={"X-Request-Id": "trace-route-bind"},
        body=_xml(msg_id="route-bind-message", content=state, create_time=now),
    )
    response = await platform_router.WechatOfficialAccountCallbackApi().post(request, "oa-route-bind")

    assert response.status == 200
    assert "绑定成功" in response.body.decode()
    confirm.assert_awaited_once()
    assert confirm.await_args.kwargs["state"] == state
    assert confirm.await_args.kwargs["external_identity_id"] == "openid_test"
    # The one-time secret is never stored as message content or queued for ADP.
    record_inbound.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_binding_code_reports_failure_without_enqueue(monkeypatch):
    from test.app_bootstrap import ensure_app

    ensure_app()
    import router.platform as platform_router

    now = int(time.time())
    token = "token-route-bind-bad"
    nonce = "nonce-route-bind-bad-1"
    state = "pci_" + "c" * 43
    record_inbound = AsyncMock()

    async def fake_credential(_db, *, channel, channel_instance_id):
        return token

    monkeypatch.setattr(platform_router, "load_active_channel_instance_credential", fake_credential)
    monkeypatch.setattr(platform_router, "record_inbound_message", record_inbound)
    monkeypatch.setattr(
        platform_router,
        "confirm_channel_identity_binding",
        AsyncMock(side_effect=platform_router.PlatformBadRequest("绑定状态无效、已使用或已失效")),
    )
    _stub_callback_side_effects(monkeypatch, platform_router)

    request = SimpleNamespace(
        ctx=SimpleNamespace(db=SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())),
        args={"signature": _signature(token, str(now), nonce), "timestamp": str(now), "nonce": nonce},
        headers={"X-Request-Id": "trace-route-bind-bad"},
        body=_xml(msg_id="route-bind-bad-message", content=state, create_time=now),
    )
    response = await platform_router.WechatOfficialAccountCallbackApi().post(request, "oa-route-bind-bad")

    assert response.status == 200
    assert "绑定未成功" in response.body.decode()
    record_inbound.assert_not_awaited()
    # A rejected confirmation burns the one-time state; rolling that back would
    # let a replayed or transferred code stay usable.
    request.ctx.db.rollback.assert_not_awaited()
    request.ctx.db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_unbound_reply_is_encrypted_when_the_callback_is_encrypted(monkeypatch):
    from test.app_bootstrap import ensure_app

    ensure_app()
    import router.platform as platform_router

    now = int(time.time())
    token = "token-route-aes-unbound"
    app_id = "wx-route-aes-unbound"
    key = b"route-aes-key-012345678901234567"
    aes_key = base64.b64encode(key).decode().rstrip("=")
    nonce = "nonce-route-aes-unbound-1"
    encrypted = _encrypted_payload(xml=_xml(msg_id="aes-unbound", create_time=now), app_id=app_id, key=key)
    msg_signature = hashlib.sha1("".join(sorted((token, str(now), nonce, encrypted))).encode()).hexdigest()

    async def fake_credential(_db, *, channel, channel_instance_id):
        return json.dumps({"token": token, "appId": app_id, "encodingAesKey": aes_key})

    monkeypatch.setattr(platform_router, "load_active_channel_instance_credential", fake_credential)
    monkeypatch.setattr(platform_router, "resolve_active_channel_identity", AsyncMock(return_value=None))
    monkeypatch.setattr(platform_router, "record_inbound_message", AsyncMock())
    _stub_callback_side_effects(monkeypatch, platform_router)

    request = SimpleNamespace(
        ctx=SimpleNamespace(db=SimpleNamespace(commit=AsyncMock())),
        args={"msg_signature": msg_signature, "timestamp": str(now), "nonce": nonce, "encrypt_type": "aes"},
        headers={"X-Request-Id": "trace-route-aes-unbound"},
        body=(f"<xml><Encrypt><![CDATA[{encrypted}]]></Encrypt></xml>").encode(),
    )
    response = await platform_router.WechatOfficialAccountCallbackApi().post(request, "oa-route-aes-unbound")

    body = response.body.decode()
    assert response.status == 200
    # An encrypted callback must not be answered with cleartext guidance.
    assert "<Encrypt>" in body and "<MsgSignature>" in body
    assert "绑定" not in body

    # The platform can decrypt its own reply, proving the envelope is valid.
    adapter = WechatOfficialAccountAdapter(
        channel_instance_id="oa-route-aes-unbound",
        token=token,
        app_id=app_id,
        encoding_aes_key=aes_key,
    )
    payload = adapter.decrypt_xml(body.split("<![CDATA[", 1)[1].split("]]>", 1)[0]).decode()
    assert "绑定" in payload


def test_reply_builder_rejects_cdata_injection():
    adapter = WechatOfficialAccountAdapter(channel_instance_id="oa-cdata", token="token-cdata")
    with pytest.raises(WechatProtocolError):
        adapter.build_text_reply(
            to_open_id="openid",
            from_account="gh_test",
            content="bad]]><xml>forged</xml>",
        )


def test_normalized_reply_window_matches_customer_service_message_window():
    adapter = WechatOfficialAccountAdapter(channel_instance_id="oa-window", token="token-window")
    now = int(time.time())
    envelope = adapter.normalize_xml(body=_xml(msg_id="window-1", create_time=now), trace_id="trace", now=now)
    deadline = envelope.message.reply_window_expires_at
    assert deadline is not None
    # Measured from the sender's message, not from when processing finishes.
    expected = datetime.fromtimestamp(now, tz=timezone.utc).replace(tzinfo=None)
    assert abs((deadline - expected).total_seconds() - 48 * 60 * 60) < 2
