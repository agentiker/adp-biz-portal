"""WeCom-bot WS gateway credential-config parsing (no DB, no network)."""

from __future__ import annotations

import os

import wecom_ws_gateway as gw


def test_build_configs_reads_structured_json_credentials():
    creds = [("bot-1", '{"botId":"b-1","secret":"sec"}')]
    configs = gw.build_configs(creds)
    assert len(configs) == 1
    c = configs[0]
    assert (c.channel_instance_id, c.bot_id, c.secret) == ("bot-1", "b-1", "sec")


def test_build_configs_accepts_snake_case_aliases():
    creds = [("bot-2", '{"bot_id":"b-2","bot_secret":"s2"}')]
    configs = gw.build_configs(creds)
    assert len(configs) == 1
    assert configs[0].bot_id == "b-2" and configs[0].secret == "s2"


def test_build_configs_ignores_webhook_only_fields():
    # A WS bot may carry extra webhook/media fields; only botId + secret matter.
    creds = [("bot-3", '{"botId":"b-3","secret":"s3","token":"t","encodingAESKey":"k","corpId":"c"}')]
    configs = gw.build_configs(creds)
    assert len(configs) == 1
    assert configs[0].channel_instance_id == "bot-3"


def test_build_configs_skips_incomplete_instances():
    creds = [
        ("ok", '{"botId":"b","secret":"s"}'),
        ("no-secret", '{"botId":"b"}'),
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
