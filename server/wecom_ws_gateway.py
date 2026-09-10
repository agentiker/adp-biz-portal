#!/usr/bin/env python3
"""Run the 企业微信智能机器人 WS streaming gateway.

The AI bot delivers messages over a held WebSocket and expects the reply to
stream back on the same socket, so — unlike the durable worker — this process
holds one long-lived connection per configured bot and runs each turn inline
(:func:`run_wecom_bot_turn`) to push cumulative snapshot frames as the answer is
produced. It shares the web/worker bootstrap (config, DB engine, migration
guard, ADP provider) and reads each bot's credentials from the encrypted
channel-credential store.

Real 联调 is BLOCKED on M0-CHANNEL-01 (needs a real bot BotId/Secret and the
confirmed WS endpoint). The endpoint is overridable via ``WECOM_BOT_WS_URL`` so
联调 can point it at the verified path without a code change.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from typing import Any, Callable, Mapping

import aiohttp

from app_factory import create_app_with_configs
from core.channel_credentials import load_active_channel_credentials
from core.migration import Migration
from integrations.channels.sender_registry import _credential_fields, _first
from integrations.channels.wecom_bot.adapter import WECOM_BOT
from integrations.channels.wecom_bot.ws_client import (
    DEFAULT_WS_URL,
    WsConnection,
    WecomBotWsConfig,
    WecomBotWsGateway,
)
from util.database import create_db_engine
from worker import build_agent_provider


logger = logging.getLogger(__name__)

# Credential field aliases for the WeCom smart robot. WS long-connection needs
# only bot_id + secret; token/corpId/encodingAESKey are for the webhook/media
# path and are not required here.
CREDENTIAL_BOT_ID_KEYS = ("botId", "bot_id", "botid")
CREDENTIAL_BOT_SECRET_KEYS = ("secret", "botSecret", "bot_secret")

# Inbound frames are small; keep headroom without inviting a huge-frame DoS.
WS_MAX_MSG_SIZE = 4 * 1024 * 1024


def ws_url() -> str:
    return str(os.environ.get("WECOM_BOT_WS_URL") or DEFAULT_WS_URL).strip() or DEFAULT_WS_URL


class AiohttpWsConnection:
    """Adapt an aiohttp client websocket to the :class:`WsConnection` protocol."""

    def __init__(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        self._ws = ws

    async def send_json(self, data: Mapping[str, Any]) -> None:
        await self._ws.send_json(dict(data))

    async def receive_json(self) -> Mapping[str, Any] | None:
        while True:
            msg = await self._ws.receive()
            if msg.type == aiohttp.WSMsgType.TEXT:
                return json.loads(msg.data)
            if msg.type == aiohttp.WSMsgType.BINARY:
                return json.loads(bytes(msg.data).decode("utf-8"))
            if msg.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSING,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.ERROR,
            ):
                return None
            # PING/PONG are handled by aiohttp; keep waiting for a data frame.


def _make_connect(
    session: aiohttp.ClientSession, url: str
) -> Callable[[], Any]:
    async def connect() -> WsConnection:
        ws = await session.ws_connect(url, max_msg_size=WS_MAX_MSG_SIZE)
        return AiohttpWsConnection(ws)

    return connect


def build_configs(credentials: list[tuple[str, str]]) -> list[WecomBotWsConfig]:
    """Turn active instance credentials into usable WS configs, skipping incomplete ones."""
    configs: list[WecomBotWsConfig] = []
    for instance_id, blob in credentials:
        fields = _credential_fields(blob)
        bot_id = _first(fields, CREDENTIAL_BOT_ID_KEYS)
        secret = _first(fields, CREDENTIAL_BOT_SECRET_KEYS)
        if not (bot_id and secret):
            logger.warning(
                "wecom_bot instance %s is missing botId/secret; skipping", instance_id
            )
            continue
        configs.append(
            WecomBotWsConfig(channel_instance_id=instance_id, bot_id=bot_id, secret=secret)
        )
    return configs


async def run_gateway(args: argparse.Namespace) -> None:
    app = create_app_with_configs()
    engine, sessionmaker = create_db_engine(app)
    max_sessions = args.max_sessions if args.max_sessions and args.max_sessions > 0 else None
    try:
        async with sessionmaker() as db:
            await Migration.validate_startup(db)
            credentials = await load_active_channel_credentials(db, channel=WECOM_BOT)
        configs = build_configs(credentials)
        if not configs:
            logger.warning("no active wecom_bot channel instances configured; nothing to serve")
            return
        provider = build_agent_provider()
        url = ws_url()
        async with aiohttp.ClientSession() as session:
            gateways = [
                WecomBotWsGateway(
                    config=config, provider=provider, sessionmaker=sessionmaker,
                    connect=_make_connect(session, url),
                )
                for config in configs
            ]
            logger.info("serving %s wecom_bot ws gateway(s) against %s", len(gateways), url)
            await asyncio.gather(
                *(gateway.run_forever(max_sessions=max_sessions) for gateway in gateways)
            )
    finally:
        await engine.dispose()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the WeCom smart-robot WS streaming gateway")
    parser.add_argument(
        "--max-sessions",
        type=int,
        default=0,
        help="stop each bot after N connection sessions (0 = run forever); for smoke tests",
    )
    return parser


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    args = _parser().parse_args()
    asyncio.run(run_gateway(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
