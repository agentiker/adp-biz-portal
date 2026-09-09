"""WeCom smart-robot JSON crypt: verify/decrypt/encrypt round-trip + CorpID check."""

from __future__ import annotations

import base64
import json
import time

import pytest

from integrations.channels._wechat import crypto, crypto_json


AES_KEY_B64 = base64.b64encode(bytes(range(32))).decode().rstrip("=")
CORP = "wwcorp-1"
TOKEN = "bot-token"


def _key() -> bytes:
    return crypto.decode_aes_key(AES_KEY_B64)


def _sign(ts: str, nonce: str, encrypt: str) -> str:
    return crypto.compute_msg_signature(token=TOKEN, timestamp=ts, nonce=nonce, encrypt=encrypt)


def test_verify_and_decrypt_json_message():
    now = str(int(time.time()))
    plain = json.dumps({"msgtype": "text", "msgid": "m1", "text": {"content": "hi"}})
    encrypt = crypto.encrypt_payload(aes_key=_key(), receiver_id=CORP, plain=plain)
    body = json.dumps({"encrypt": encrypt}).encode()
    data = crypto_json.verify_and_decrypt_json(
        aes_key=_key(), corp_id=CORP, token=TOKEN, body=body,
        msg_signature=_sign(now, "n", encrypt), timestamp=now, nonce="n",
    )
    assert data["msgtype"] == "text" and data["msgid"] == "m1"

    with pytest.raises(crypto.WechatProtocolError, match="签名"):
        crypto_json.verify_and_decrypt_json(
            aes_key=_key(), corp_id=CORP, token=TOKEN, body=body,
            msg_signature="0" * 40, timestamp=now, nonce="n",
        )


def test_wrong_corpid_rejected():
    now = str(int(time.time()))
    encrypt = crypto.encrypt_payload(aes_key=_key(), receiver_id=CORP, plain="{}")
    body = json.dumps({"encrypt": encrypt}).encode()
    with pytest.raises(crypto.WechatProtocolError, match="CorpID"):
        crypto_json.verify_and_decrypt_json(
            aes_key=_key(), corp_id="other", token=TOKEN, body=body,
            msg_signature=_sign(now, "n", encrypt), timestamp=now, nonce="n",
        )


def test_build_reply_json_roundtrips():
    now = str(int(time.time()))
    reply = crypto_json.build_reply_json(
        aes_key=_key(), corp_id=CORP, token=TOKEN, plain='{"msgtype":"stream"}', timestamp=now, nonce="rn"
    )
    assert set(reply) == {"encrypt", "msgsignature", "timestamp", "nonce"}
    # The reply signature verifies and the payload decrypts back.
    assert crypto.verify_msg_signature(
        token=TOKEN, timestamp=now, nonce="rn", encrypt=reply["encrypt"], msg_signature=reply["msgsignature"]
    )
    out = crypto.decrypt_envelope(aes_key=_key(), encrypt=reply["encrypt"], expected_receiver_id=CORP)
    assert out.decode() == '{"msgtype":"stream"}'


def test_verify_url_json_echo():
    now = str(int(time.time()))
    echo = crypto.encrypt_payload(aes_key=_key(), receiver_id=CORP, plain="echo-1")
    assert crypto_json.verify_url_json(
        aes_key=_key(), corp_id=CORP, token=TOKEN,
        msg_signature=_sign(now, "n", echo), timestamp=now, nonce="n", echostr=echo,
    ) == "echo-1"
