"""WeChat 客服 router callback: GET verify echo, POST ack + enqueue pull task."""

from __future__ import annotations

import base64
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from integrations.channels._wechat import crypto


AES_KEY_B64 = base64.b64encode(bytes(range(32))).decode().rstrip("=")
CORP = "corp-kf"
TOKEN = "kf-callback-token"
CREDENTIAL = json.dumps({"corpId": CORP, "token": TOKEN, "encodingAESKey": AES_KEY_B64})


def _sign(ts: str, nonce: str, encrypt: str) -> str:
    return crypto.compute_msg_signature(token=TOKEN, timestamp=ts, nonce=nonce, encrypt=encrypt)


def _encrypt(plain: str) -> str:
    return crypto.encrypt_payload(aes_key=crypto.decode_aes_key(AES_KEY_B64), receiver_id=CORP, plain=plain)


@pytest.mark.asyncio
async def test_kf_get_verifies_and_returns_decrypted_echo(monkeypatch):
    from test.app_bootstrap import ensure_app

    ensure_app()
    import router.platform as platform_router

    monkeypatch.setattr(platform_router, "load_active_channel_instance_credential", AsyncMock(return_value=CREDENTIAL))
    now = int(time.time())
    echo = _encrypt("echo-plain")
    request = SimpleNamespace(
        ctx=SimpleNamespace(db=SimpleNamespace(commit=AsyncMock())),
        args={"msg_signature": _sign(str(now), "n", echo), "timestamp": str(now), "nonce": "n", "echostr": echo},
        headers={"X-Request-Id": "kf-trace"},
    )
    response = await platform_router.WechatKfCallbackApi().get(request, "kf-1")
    assert response.body.decode() == "echo-plain"


@pytest.mark.asyncio
async def test_kf_post_acks_and_enqueues_pull_task(monkeypatch):
    from test.app_bootstrap import ensure_app

    ensure_app()
    import router.platform as platform_router

    monkeypatch.setattr(platform_router, "load_active_channel_instance_credential", AsyncMock(return_value=CREDENTIAL))
    enqueue = AsyncMock(return_value=(SimpleNamespace(Id="t"), True))
    monkeypatch.setattr(platform_router, "enqueue_delivery_task", enqueue)

    now = int(time.time())
    plain = json.dumps({"Token": "pull-tok", "OpenKfId": "wkAAA"})
    encrypt = _encrypt(plain)
    body = json.dumps({"encrypt": encrypt}).encode()
    request = SimpleNamespace(
        ctx=SimpleNamespace(db=SimpleNamespace(commit=AsyncMock())),
        args={"msg_signature": _sign(str(now), "n2", encrypt), "timestamp": str(now), "nonce": "n2"},
        headers={"X-Request-Id": "kf-trace"},
        body=body,
    )
    response = await platform_router.WechatKfCallbackApi().post(request, "kf-1")

    assert response.body.decode() == "success"
    enqueue.assert_awaited_once()
    kwargs = enqueue.await_args.kwargs
    assert kwargs["task_type"] == platform_router.PLATFORM_CHANNEL_PULL_TASK_TYPE
    assert kwargs["payload"]["openKfId"] == "wkAAA"
    assert kwargs["payload"]["callbackToken"] == "pull-tok"
    assert kwargs["payload"]["channelInstanceId"] == "kf-1"
    request.ctx.db.commit.assert_awaited_once()
