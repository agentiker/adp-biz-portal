"""Shared WeChat/WeCom crypto core: round-trip, signatures, receiver check."""

from __future__ import annotations

import base64

import pytest

from integrations.channels._wechat import crypto


_RAW_KEY = bytes(range(32))
AES_KEY_B64 = base64.b64encode(_RAW_KEY).decode().rstrip("=")  # 43 chars, WeChat form


def _key() -> bytes:
    return crypto.decode_aes_key(AES_KEY_B64)


def test_decode_aes_key_valid_and_invalid():
    assert crypto.decode_aes_key(AES_KEY_B64) == _RAW_KEY
    for bad in ["", "   ", "short", "x" * 50]:
        with pytest.raises(ValueError):
            crypto.decode_aes_key(bad)


def test_plaintext_signature_roundtrip():
    sig_ok = crypto.compute_msg_signature(token="tok", timestamp="100", nonce="n", encrypt="E")
    assert crypto.verify_msg_signature(token="tok", timestamp="100", nonce="n", encrypt="E", msg_signature=sig_ok)
    assert not crypto.verify_msg_signature(token="tok", timestamp="100", nonce="n", encrypt="E", msg_signature="deadbeef")


def test_verify_signature_get_handshake():
    import hashlib

    token, ts, nonce = "tok", "1700000000", "nonce123"
    good = hashlib.sha1("".join(sorted((token, ts, nonce))).encode()).hexdigest()
    assert crypto.verify_signature(token=token, timestamp=ts, nonce=nonce, signature=good)
    assert not crypto.verify_signature(token=token, timestamp=ts, nonce=nonce, signature="0" * 40)


def test_envelope_roundtrip_and_receiver_check():
    key = _key()
    plain = "<xml><Content>货物已到港</Content></xml>"
    encrypted = crypto.encrypt_payload(aes_key=key, receiver_id="corp-1", plain=plain)

    # Correct receiver decrypts back to the exact plaintext.
    out = crypto.decrypt_envelope(aes_key=key, encrypt=encrypted, expected_receiver_id="corp-1")
    assert out.decode("utf-8") == plain

    # Wrong receiver id is rejected, with a label-shaped message.
    with pytest.raises(crypto.WechatProtocolError, match="CorpID"):
        crypto.decrypt_envelope(
            aes_key=key, encrypt=encrypted, expected_receiver_id="other", receiver_label="CorpID"
        )

    # receiver_id=None skips the trailer check (still decrypts).
    assert crypto.decrypt_envelope(aes_key=key, encrypt=encrypted, expected_receiver_id=None).decode() == plain


def test_decrypt_rejects_garbage():
    key = _key()
    with pytest.raises(crypto.WechatProtocolError):
        crypto.decrypt_envelope(aes_key=key, encrypt="not-base64!!", expected_receiver_id=None)
    with pytest.raises(crypto.WechatProtocolError):
        crypto.decrypt_envelope(aes_key=key, encrypt="", expected_receiver_id=None)


def test_parse_xml_rejects_entities_and_bad_root():
    with pytest.raises(crypto.WechatProtocolError):
        crypto.parse_xml(b"<!DOCTYPE x><xml></xml>")
    with pytest.raises(crypto.WechatProtocolError):
        crypto.parse_xml(b"<notxml></notxml>")
    root = crypto.parse_xml(b"<xml><A>1</A></xml>")
    assert crypto.xml_value(root, "A") == "1"


def test_cdata_rejects_injection():
    assert crypto.cdata("hello", field="x") == "hello"
    with pytest.raises(crypto.WechatProtocolError):
        crypto.cdata("a]]>b", field="x")
