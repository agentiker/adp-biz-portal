"""WeCom-bot WS gateway credential-config parsing (no DB, no network)."""

from __future__ import annotations

import os

import wecom_ws_gateway as gw


def test_build_configs_reads_structured_json_credentials():
    creds = [(
        "bot-1",
        '{"botId":"b-1","secret":"sec","corpId":"corp-1","token":"tok","encodingAESKey":"key"}',
    )]
    configs = gw.build_configs(creds)
    assert len(configs) == 1
    c = configs[0]
    assert (c.channel_instance_id, c.bot_id, c.secret) == ("bot-1", "b-1", "sec")
    assert (c.corp_id, c.token, c.encoding_aes_key) == ("corp-1", "tok", "key")


def test_build_configs_accepts_snake_case_aliases():
    creds = [(
        "bot-2",
        '{"bot_id":"b-2","bot_secret":"s2","corp_id":"c2","callback_token":"t2","encoding_aes_key":"k2"}',
    )]
    configs = gw.build_configs(creds)
    assert len(configs) == 1
    assert configs[0].bot_id == "b-2" and configs[0].token == "t2"


def test_build_configs_skips_incomplete_instances():
    creds = [
        ("ok", '{"botId":"b","secret":"s","corpId":"c","token":"t","encodingAESKey":"k"}'),
        ("no-secret", '{"botId":"b","corpId":"c","token":"t","encodingAESKey":"k"}'),
        ("garbage", "not-json"),
    ]
    configs = gw.build_configs(creds)
    assert [c.channel_instance_id for c in configs] == ["ok"]


def test_ws_url_prefers_env_override(monkeypatch):
    monkeypatch.delenv("WECOM_BOT_WS_URL", raising=False)
    assert gw.ws_url() == gw.DEFAULT_WS_URL
    monkeypatch.setenv("WECOM_BOT_WS_URL", "wss://example.test/path")
    assert gw.ws_url() == "wss://example.test/path"
    monkeypatch.setenv("WECOM_BOT_WS_URL", "   ")
    assert gw.ws_url() == gw.DEFAULT_WS_URL
