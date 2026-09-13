"""WeCom smart-robot message normalization: text-only, session scoping."""

from __future__ import annotations

import base64

import pytest

from integrations.channels.wecom_bot.adapter import WecomBotAdapter, WecomBotInboundEnvelope


AES_KEY_B64 = base64.b64encode(bytes(range(32))).decode().rstrip("=")


def _adapter() -> WecomBotAdapter:
    return WecomBotAdapter(channel_instance_id="bot-1", corp_id="corp-1", token="tok", encoding_aes_key=AES_KEY_B64)


def test_single_chat_text_normalizes_and_scopes_by_user():
    env = _adapter().normalize_message(
        {"msgtype": "text", "msgid": "m1", "chattype": "single", "from": {"userid": "u1"}, "text": {"content": "BL-1"}, "stream": {"id": "s1"}},
        trace_id="t",
    )
    assert isinstance(env, WecomBotInboundEnvelope)
    assert env.message.external_message_id == "m1"
    assert env.message.text == "BL-1"
    assert env.message.sender_identity_id == "u1"
    assert env.message.external_conversation_id == "bot-1:u1"
    assert env.stream_id == "s1"
    assert env.get_launcher_id() == "u1"


def test_group_chat_scopes_by_chat_id():
    env = _adapter().normalize_message(
        {"msgtype": "text", "msgid": "m2", "chattype": "group", "chatid": "c9", "from": {"userid": "u1"}, "text": {"content": "hi"}},
        trace_id="t",
    )
    assert env.message.external_conversation_id == "bot-1:c9"
    assert env.get_launcher_id() == "c9"


def test_non_text_and_empty_are_skipped():
    a = _adapter()
    assert a.normalize_message({"msgtype": "image", "from": {"userid": "u"}}, trace_id="t") is None
    assert a.normalize_message({"msgtype": "text", "from": {"userid": "u"}, "text": {"content": ""}}, trace_id="t") is None
    assert a.normalize_message({"msgtype": "text", "text": {"content": "hi"}}, trace_id="t") is None  # no userid
