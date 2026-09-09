"""Shared WeChat/WeCom callback crypto (XML and JSON envelopes).

The signature scheme and AES envelope are identical across 微信公众号,
微信客服 and 企业微信智能机器人 — only the trailing ``receiver_id`` (AppID for
the official account, CorpID for WeCom) and the outer envelope (XML vs JSON)
differ. This module owns the one implementation of that core so no adapter
copies it. Pure functions only: no network, no DB, no per-channel state.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import struct
import threading
import xml.etree.ElementTree as ET
from typing import Any

from core.error.platform import PlatformBadRequest


MAX_XML_BYTES = 256 * 1024
MAX_ENCRYPT_CHARS = 512 * 1024
_AES_BLOCK = 32


class WechatProtocolError(PlatformBadRequest):
    """Malformed or unauthenticated provider callback."""


def decode_aes_key(value: str | None) -> bytes:
    """Decode a WeChat EncodingAESKey (43 base64 chars, no padding) to 32 bytes."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("encoding_aes_key is required")
    encoded = value.strip()
    if len(encoded) not in (43, 44):
        raise ValueError("encoding_aes_key has an invalid length")
    try:
        key = base64.b64decode(encoded + "=" * (-len(encoded) % 4), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("encoding_aes_key is not valid base64") from exc
    if len(key) != 32:
        raise ValueError("encoding_aes_key must decode to 32 bytes")
    return key


def verify_signature(*, token: str, timestamp: str, nonce: str, signature: str) -> bool:
    """Verify a plaintext GET handshake signature (sorted SHA1 of 3 values)."""
    if not all(isinstance(value, str) and value for value in (token, timestamp, nonce, signature)):
        return False
    if len(timestamp) > 32 or len(nonce) > 128 or len(signature) != 40:
        return False
    expected = hashlib.sha1("".join(sorted((token, timestamp, nonce))).encode("utf-8")).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


def compute_msg_signature(*, token: str, timestamp: str, nonce: str, encrypt: str) -> str:
    """Sorted SHA1 of the 4-tuple used for encrypted callbacks and replies."""
    return hashlib.sha1("".join(sorted((token, str(timestamp), nonce, encrypt))).encode("utf-8")).hexdigest()


def verify_msg_signature(*, token: str, timestamp: str, nonce: str, encrypt: str, msg_signature: str) -> bool:
    if not isinstance(msg_signature, str) or not msg_signature:
        return False
    expected = compute_msg_signature(token=token, timestamp=timestamp, nonce=nonce, encrypt=encrypt)
    return hmac.compare_digest(expected, msg_signature.lower())


def check_timestamp(value: Any, *, now: float, window_seconds: int) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise WechatProtocolError("微信回调时间戳格式不正确") from exc
    if abs(now - parsed) > window_seconds:
        raise WechatProtocolError("微信回调已超出允许时间窗口")
    return parsed


def decrypt_envelope(
    *, aes_key: bytes, encrypt: str, expected_receiver_id: str | None, receiver_label: str = "接收方"
) -> bytes:
    """Decrypt a WeChat AES-256-CBC envelope and validate its trailing receiver id.

    Layout after PKCS7(32) unpad: ``random16 | msgLen(4, big-endian) | msg |
    receiver_id``. ``expected_receiver_id`` is the AppID (official account) or
    CorpID (WeCom); a mismatch is rejected. ``receiver_label`` only shapes the
    error text (e.g. "AppID" / "CorpID"). Returns the raw ``msg`` bytes.
    """
    if not isinstance(encrypt, str) or not encrypt or len(encrypt) > MAX_ENCRYPT_CHARS:
        raise WechatProtocolError("微信加密回调内容无效")
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        ciphertext = base64.b64decode(encrypt, validate=True)
        decryptor = Cipher(algorithms.AES(aes_key), modes.CBC(aes_key[:16])).decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
    except (ValueError, binascii.Error) as exc:
        raise WechatProtocolError("微信加密回调无法解密") from exc
    if not padded or len(padded) % _AES_BLOCK:
        raise WechatProtocolError("微信加密回调填充无效")
    pad_length = padded[-1]
    if not 1 <= pad_length <= _AES_BLOCK or padded[-pad_length:] != bytes([pad_length]) * pad_length:
        raise WechatProtocolError("微信加密回调填充无效")
    payload = padded[:-pad_length]
    if len(payload) < 20:
        raise WechatProtocolError("微信加密回调内容不完整")
    message_length = struct.unpack("!I", payload[16:20])[0]
    message_end = 20 + message_length
    if message_end > len(payload):
        raise WechatProtocolError("微信加密回调消息长度无效")
    message = payload[20:message_end]
    try:
        receiver = payload[message_end:].decode("utf-8")
        message.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WechatProtocolError("微信加密回调编码无效") from exc
    if expected_receiver_id is not None and receiver != expected_receiver_id:
        raise WechatProtocolError(f"微信加密回调{receiver_label}不匹配")
    return message


def encrypt_payload(*, aes_key: bytes, receiver_id: str, plain: str) -> str:
    """Encrypt ``plain`` into a WeChat AES-256-CBC envelope, base64-encoded."""
    if not isinstance(plain, str) or not plain:
        raise WechatProtocolError("微信回复内容无效")
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    body = plain.encode("utf-8")
    payload = secrets.token_bytes(16) + struct.pack("!I", len(body)) + body + receiver_id.encode("utf-8")
    pad_length = _AES_BLOCK - (len(payload) % _AES_BLOCK)
    padded = payload + bytes([pad_length]) * pad_length
    encryptor = Cipher(algorithms.AES(aes_key), modes.CBC(aes_key[:16])).encryptor()
    return base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode("ascii")


def xml_value(root: ET.Element, name: str, *, required: bool = False) -> str:
    value = root.findtext(name)
    value = value.strip() if isinstance(value, str) else ""
    if required and not value:
        raise WechatProtocolError(f"微信回调缺少{name}")
    return value


def parse_xml(body: bytes) -> ET.Element:
    if not isinstance(body, (bytes, bytearray)) or not body or len(body) > MAX_XML_BYTES:
        raise WechatProtocolError("微信回调 XML 无效")
    lowered = bytes(body).lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise WechatProtocolError("微信回调 XML 不允许实体声明")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise WechatProtocolError("微信回调 XML 无效") from exc
    if root.tag.rsplit("}", 1)[-1] != "xml":
        raise WechatProtocolError("微信回调 XML 根节点无效")
    return root


def extract_encrypted_xml(body: bytes) -> str:
    encrypted = xml_value(parse_xml(body), "Encrypt", required=True)
    if len(encrypted) > MAX_ENCRYPT_CHARS:
        raise WechatProtocolError("微信加密回调内容过大")
    return encrypted


def cdata(value: Any, *, field: str, max_length: int = 255) -> str:
    """Return text safe to embed in a CDATA section (rejects ``]]>`` + controls)."""
    if not isinstance(value, str) or not value.strip():
        raise WechatProtocolError(f"微信{field}格式不正确")
    normalized = value.strip()
    if len(normalized) > max_length:
        raise WechatProtocolError(f"微信{field}长度超限")
    if "]]>" in normalized or any(ord(char) < 0x20 and char not in "\r\n\t" for char in normalized):
        raise WechatProtocolError(f"微信{field}包含不支持的字符")
    return normalized


class ReplayGuard:
    """Process-local replay cache used as a fast path.

    Durable, cross-instance rejection comes from ``core.channel_replay``; this
    only short-circuits obvious repeats within one process.
    """

    def __init__(self, *, max_entries: int = 20_000) -> None:
        self._entries: dict[str, float] = {}
        self._lock = threading.Lock()
        self._max_entries = max_entries

    def check_and_mark(self, key: str, *, now: float, ttl: int) -> bool:
        with self._lock:
            cutoff = now - ttl
            self._entries = {item: stamp for item, stamp in self._entries.items() if stamp >= cutoff}
            if key in self._entries:
                return False
            if len(self._entries) >= self._max_entries:
                oldest = min(self._entries, key=self._entries.get)
                self._entries.pop(oldest, None)
            self._entries[key] = now
            return True


# Shared across channels; replay keys embed the channel instance id.
replay_guard = ReplayGuard()
