"""企业微信智能机器人 WS long-connection client (real streaming).

The AI bot pushes inbound messages over a WebSocket (``wss://openws.work.weixin.qq.com``)
and expects the reply to stream back on the *same* socket as cumulative
snapshot frames. That rules out the durable worker (which cannot push to a held
socket): this client holds the connection and runs each turn inline via
``run_wecom_bot_turn``, whose ``reply_stream`` closure encrypts each snapshot
into a reply frame and sends it straight back.

Connection lifecycle here (subscribe / heartbeat / reconnect) and the callback
crypto (``_wechat.crypto_json``) are protocol-verified against the reference
impls and docs. The exact *reply* frame field names cannot be confirmed without
a live bot, so they are centralized as constants (``REPLY_*``) — real 联调
(M0-CHANNEL-01) may need to adjust only those. The transport is injected as a
``connect`` callable returning a :class:`WsConnection`, so the whole dispatch
path is exercised by a fake ws in tests without any network.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Protocol

from integrations.channels._wechat.crypto import WechatProtocolError
from integrations.channels._wechat.crypto_json import build_reply_json, verify_and_decrypt_json
from integrations.channels.wecom_bot.adapter import WecomBotAdapter
from integrations.channels.wecom_bot.gateway import _MsgidGuard, run_wecom_bot_turn


logger = logging.getLogger(__name__)

# Outbound command names on the socket.
CMD_SUBSCRIBE = "aibot_subscribe"
CMD_PING = "ping"
CMD_REPLY = "reply_stream"
# Inbound frame markers.
CMD_CALLBACK = "aibot_msg_callback"
# Reply-frame field names (see module docstring — adjust here after 联调).
REPLY_STREAM_ID = "stream_id"
REPLY_REQ_ID = "req_id"
REPLY_FINISH = "finish"
REPLY_CONTENT = "content"

DEFAULT_HEARTBEAT_INTERVAL = 30.0
# errcode 6000 = a subscribe for this bot already holds the socket elsewhere.
CONFLICT_ERRCODE = 6000
_BACKOFF_BASE = 1.0
_BACKOFF_MAX = 30.0


class WsSubscribeConflict(RuntimeError):
    """Raised when another subscriber already holds this bot's socket."""


class WsConnection(Protocol):
    """Minimal duplex text-frame connection (aiohttp ws or a test fake)."""

    async def send_json(self, data: Mapping[str, Any]) -> None: ...

    async def receive_json(self) -> Mapping[str, Any] | None:
        """Return the next inbound frame, or ``None`` when the socket closes."""
        ...

    async def close(self) -> None: ...


@dataclass(frozen=True)
class WecomBotWsConfig:
    channel_instance_id: str
    bot_id: str
    secret: str
    corp_id: str
    token: str
    encoding_aes_key: str


class WecomBotWsGateway:
    """Hold one bot's WS session and stream replies back inline."""

    def __init__(
        self,
        *,
        config: WecomBotWsConfig,
        provider: Any,
        sessionmaker: Callable[[], Any],
        connect: Callable[[], Awaitable[WsConnection]],
        heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL,
        guard: _MsgidGuard | None = None,
        now: Callable[[], float] = time.time,
    ):
        self._config = config
        self._provider = provider
        self._sessionmaker = sessionmaker
        self._connect = connect
        self._heartbeat_interval = max(1.0, heartbeat_interval)
        self._guard = guard or _MsgidGuard()
        self._now = now
        self._adapter = WecomBotAdapter(
            channel_instance_id=config.channel_instance_id,
            corp_id=config.corp_id,
            token=config.token,
            encoding_aes_key=config.encoding_aes_key,
        )

    async def run_forever(self, *, max_sessions: int | None = None) -> None:
        """Serve sessions, reconnecting with capped exponential backoff."""
        attempt = 0
        sessions = 0
        while max_sessions is None or sessions < max_sessions:
            sessions += 1
            try:
                await self.serve_once()
                attempt = 0  # a clean session resets backoff
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a session must never kill the loop
                attempt += 1
                logger.warning(
                    "wecom bot ws session ended (%s); reconnecting", type(exc).__name__
                )
            if max_sessions is not None and sessions >= max_sessions:
                break
            delay = min(_BACKOFF_MAX, _BACKOFF_BASE * (2 ** min(attempt, 6)))
            await asyncio.sleep(delay)

    async def serve_once(self) -> None:
        """Run one connection: subscribe, heartbeat, and dispatch until closed."""
        conn = await self._connect()
        stop = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat(conn, stop))
        try:
            await self._subscribe(conn)
            while True:
                frame = await conn.receive_json()
                if frame is None:
                    break
                try:
                    await self._dispatch(conn, frame)
                except Exception:  # noqa: BLE001 - one bad frame must not drop the socket
                    logger.exception("wecom bot ws frame dispatch failed")
        finally:
            stop.set()
            heartbeat.cancel()
            try:
                await heartbeat
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            await conn.close()

    async def _subscribe(self, conn: WsConnection) -> None:
        await conn.send_json(
            {"cmd": CMD_SUBSCRIBE, "bot_id": self._config.bot_id, "secret": self._config.secret}
        )

    async def _heartbeat(self, conn: WsConnection, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._heartbeat_interval)
                return
            except asyncio.TimeoutError:
                pass
            try:
                await conn.send_json({"cmd": CMD_PING})
            except Exception:  # noqa: BLE001 - the receive loop will observe the close
                return

    async def _dispatch(self, conn: WsConnection, frame: Mapping[str, Any]) -> None:
        errcode = frame.get("errcode")
        if isinstance(errcode, int) and errcode not in (0, None):
            if errcode == CONFLICT_ERRCODE:
                raise WsSubscribeConflict("aibot_subscribe conflict (errcode 6000)")
            logger.warning("wecom bot ws control frame errcode=%s", errcode)
            return
        encrypt = frame.get("encrypt") or frame.get("Encrypt")
        if not encrypt:
            # subscribe ack / pong / other control frame — nothing to answer.
            return
        await self._handle_callback(conn, frame)

    async def _handle_callback(self, conn: WsConnection, frame: Mapping[str, Any]) -> None:
        msg_signature = str(frame.get("msgsignature") or frame.get("msg_signature") or "")
        timestamp = str(frame.get("timestamp") or "")
        nonce = str(frame.get("nonce") or "")
        req_id = str(frame.get(REPLY_REQ_ID) or frame.get("reqid") or "")
        body = json.dumps({"encrypt": frame.get("encrypt") or frame.get("Encrypt")}).encode("utf-8")
        try:
            message = verify_and_decrypt_json(
                aes_key=self._adapter.aes_key,
                corp_id=self._config.corp_id,
                token=self._config.token,
                body=body,
                msg_signature=msg_signature,
                timestamp=timestamp,
                nonce=nonce,
            )
        except WechatProtocolError as exc:
            logger.warning("wecom bot callback rejected: %s", exc)
            return

        trace_id = str(message.get("msgid") or f"wecom-bot-{secrets.token_hex(6)}")
        envelope = self._adapter.normalize_message(message, trace_id=trace_id, now=self._now())
        if envelope is None:
            return  # non-text or empty — nothing to stream back

        stream_id = envelope.stream_id or req_id or trace_id
        reply_stream = self._reply_stream(conn, stream_id=stream_id, req_id=req_id)
        await run_wecom_bot_turn(
            self._sessionmaker,
            channel=self._adapter.channel,
            channel_instance_id=self._config.channel_instance_id,
            envelope=envelope,
            provider=self._provider,
            reply_stream=reply_stream,
            now=self._now(),
            guard=self._guard,
        )

    def _reply_stream(
        self, conn: WsConnection, *, stream_id: str, req_id: str
    ) -> Callable[..., Awaitable[None]]:
        cfg = self._config
        adapter = self._adapter

        async def reply_stream(content: str, *, is_final: bool) -> None:
            ts = str(int(self._now()))
            nonce = secrets.token_hex(8)
            plain = json.dumps(
                {
                    "msgtype": "stream",
                    "stream": {
                        REPLY_STREAM_ID: stream_id,
                        REPLY_FINISH: bool(is_final),
                        REPLY_CONTENT: content,
                    },
                },
                ensure_ascii=False,
            )
            envelope = build_reply_json(
                aes_key=adapter.aes_key, corp_id=cfg.corp_id, token=cfg.token,
                plain=plain, timestamp=ts, nonce=nonce,
            )
            frame = {"cmd": CMD_REPLY, REPLY_REQ_ID: req_id, REPLY_STREAM_ID: stream_id, **envelope}
            await conn.send_json(frame)

        return reply_stream
