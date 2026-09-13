"""WeCom smart-robot (企业微信智能机器人) JSON callback crypto.

The AI-bot callback body is JSON (``{"encrypt": ...}``), not the XML ``<xml>``
envelope, so wechatpy's XML ``WXBizMsgCrypt`` cannot parse it. Only the outer
wrapper differs — the AES envelope, sorted-SHA1 signature and receiver_id
(CorpID) trailer are identical to the XML path — so this module reuses the
shared core in ``_wechat.crypto`` and only handles the JSON wrapper. The real
CorpID is always passed to the receiver check (unlike the reference impls that
pass an empty string and skip it).
"""

from __future__ import annotations

import json
from typing import Any

from integrations.channels._wechat.crypto import (
    WechatProtocolError,
    compute_msg_signature,
    decrypt_envelope,
    encrypt_payload,
    verify_msg_signature,
)


def extract_encrypted_json(body: bytes) -> str:
    if not isinstance(body, (bytes, bytearray)) or not body:
        raise WechatProtocolError("企微机器人回调为空")
    try:
        payload = json.loads(bytes(body).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise WechatProtocolError("企微机器人回调 JSON 无效") from exc
    encrypt = payload.get("encrypt") or payload.get("Encrypt")
    if not isinstance(encrypt, str) or not encrypt:
        raise WechatProtocolError("企微机器人回调缺少 encrypt")
    return encrypt


def verify_and_decrypt_json(
    *, aes_key: bytes, corp_id: str, token: str, body: bytes, msg_signature: str, timestamp: str, nonce: str
) -> dict[str, Any]:
    """Verify + decrypt a JSON callback body, returning the parsed message dict."""
    encrypt = extract_encrypted_json(body)
    if not verify_msg_signature(
        token=token, timestamp=str(timestamp), nonce=nonce, encrypt=encrypt, msg_signature=msg_signature
    ):
        raise WechatProtocolError("企微机器人回调签名无效")
    plain = decrypt_envelope(
        aes_key=aes_key, encrypt=encrypt, expected_receiver_id=corp_id, receiver_label="CorpID"
    )
    try:
        data = json.loads(plain.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise WechatProtocolError("企微机器人消息 JSON 无效") from exc
    if not isinstance(data, dict):
        raise WechatProtocolError("企微机器人消息 JSON 无效")
    return data


def verify_url_json(
    *, aes_key: bytes, corp_id: str, token: str, msg_signature: str, timestamp: str, nonce: str, echostr: str
) -> str:
    """Verify the GET URL handshake and return the decrypted echostr plaintext."""
    if not verify_msg_signature(
        token=token, timestamp=str(timestamp), nonce=nonce, encrypt=echostr, msg_signature=msg_signature
    ):
        raise WechatProtocolError("企微机器人回调签名无效")
    try:
        return decrypt_envelope(
            aes_key=aes_key, encrypt=echostr, expected_receiver_id=corp_id, receiver_label="CorpID"
        ).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WechatProtocolError("echostr解密结果无效") from exc


def build_reply_json(
    *, aes_key: bytes, corp_id: str, token: str, plain: str, timestamp: str, nonce: str
) -> dict[str, str]:
    """Encrypt a reply into the AI-bot JSON envelope."""
    encrypt = encrypt_payload(aes_key=aes_key, receiver_id=corp_id, plain=plain)
    signature = compute_msg_signature(token=token, timestamp=str(timestamp), nonce=nonce, encrypt=encrypt)
    return {"encrypt": encrypt, "msgsignature": signature, "timestamp": str(timestamp), "nonce": nonce}
