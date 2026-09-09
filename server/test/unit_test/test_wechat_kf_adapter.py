"""WeChat 客服 adapter: echo verify, notification extraction, normalization."""

from __future__ import annotations

import base64
import json
import time

import pytest

from integrations.channels._wechat import crypto
from integrations.channels.wechat_kf.adapter import WechatKfAdapter, WechatKfInboundEnvelope


AES_KEY_B64 = base64.b64encode(bytes(range(32))).decode().rstrip("=")
CORP = "corp-1"
TOKEN = "kf-token"


def _adapter() -> WechatKfAdapter:
    return WechatKfAdapter(
        channel_instance_id="kf-1", corp_id=CORP, token=TOKEN, encoding_aes_key=AES_KEY_B64
    )


def _sign(ts: str, nonce: str, encrypt: str) -> str:
    return crypto.compute_msg_signature(token=TOKEN, timestamp=ts, nonce=nonce, encrypt=encrypt)


def _encrypt(plain: str) -> str:
    key = crypto.decode_aes_key(AES_KEY_B64)
    return crypto.encrypt_payload(aes_key=key, receiver_id=CORP, plain=plain)


def test_verify_echo_returns_decrypted_plaintext():
    adapter = _adapter()
    now = 1_700_000_000
    echo = _encrypt("echo-plaintext")
    sig = _sign(str(now), "n1", echo)
    assert adapter.verify_echo(msg_signature=sig, timestamp=str(now), nonce="n1", echostr=echo, now=now) == "echo-plaintext"
    with pytest.raises(crypto.WechatProtocolError, match="签名"):
        adapter.verify_echo(msg_signature="0" * 40, timestamp=str(now), nonce="n1", echostr=echo, now=now)


@pytest.mark.parametrize("as_json", [True, False])
def test_verify_and_extract_notification_json_and_xml(as_json):
    adapter = _adapter()
    now = 1_700_000_100
    if as_json:
        plain = json.dumps({"Token": "pull-tok", "OpenKfId": "wkAAA"})
    else:
        plain = "<xml><Token>pull-tok</Token><OpenKfId>wkAAA</OpenKfId></xml>"
    encrypt = _encrypt(plain)
    body = json.dumps({"encrypt": encrypt}).encode() if as_json else f"<xml><Encrypt>{encrypt}</Encrypt></xml>".encode()
    sig = _sign(str(now), "n2", encrypt)
    token, open_kfid = adapter.verify_and_extract_notification(
        body=body, msg_signature=sig, timestamp=str(now), nonce="n2", now=now
    )
    assert (token, open_kfid) == ("pull-tok", "wkAAA")
    # Replay of the same signature is rejected.
    with pytest.raises(crypto.WechatProtocolError, match="重复"):
        adapter.verify_and_extract_notification(
            body=body, msg_signature=sig, timestamp=str(now), nonce="n2", now=now
        )


def test_normalize_only_customer_text():
    adapter = _adapter()
    now = 1_700_000_200
    item = {
        "msgid": "m1", "open_kfid": "wkAAA", "external_userid": "wmUser",
        "origin": 3, "msgtype": "text", "text": {"content": "BL-123"}, "send_time": now,
    }
    env = adapter.normalize_item(item, trace_id="t", now=now)
    assert isinstance(env, WechatKfInboundEnvelope)
    assert env.message.external_message_id == "m1"
    assert env.message.text == "BL-123"
    assert env.message.sender_identity_id == "wmUser"
    assert env.message.external_conversation_id == "kf-1:wkAAA:wmUser"
    assert env.get_launcher_id() == "wkAAA|wmUser"
    assert env.message.reply_window_expires_at is not None

    # Non-customer origin, non-text, and missing fields are all skipped.
    assert adapter.normalize_item({**item, "origin": 4}, trace_id="t", now=now) is None
    assert adapter.normalize_item({**item, "msgtype": "image"}, trace_id="t", now=now) is None
    assert adapter.normalize_item({**item, "text": {"content": ""}}, trace_id="t", now=now) is None
