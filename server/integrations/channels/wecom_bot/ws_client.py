"""企业微信智能机器人 WS long-connection client (real streaming).

The AI bot delivers inbound messages over a WebSocket to
``wss://openws.work.weixin.qq.com`` and expects the reply to stream back on the
*same* socket. That rules out the durable worker (which cannot push to a held
socket): this client holds the connection and runs each turn inline via
``run_wecom_bot_turn``, whose ``reply_stream`` closure sends each cumulative
snapshot straight back as an ``aibot_respond_msg`` frame.

Protocol (verified against three reference impls — AstrBot ``wecomai_long_connection.py``,
LangBot ``wecom_ai_bot_api/ws_client.py`` and openclaw-china's long-connection
spec — which all agree):

- Bare URL ``wss://openws.work.weixin.qq.com``; on connect send ``aibot_subscribe``
  with ``{"bot_id","secret"}``. One bot holds at most one live connection; a new
  one evicts the old.
- Every frame is ``{"cmd", "headers": {"req_id"}, "body": {...}}``. Heartbeat is
  ``ping``; inbound is ``aibot_msg_callback`` / ``aibot_event_callback``.
- In long-connection mode the callback ``body`` is **plaintext** (TLS secures
  the socket) — there is no per-frame AES/signature. AES only applies to the
  separate HTTPS-webhook mode and to per-URL media keys, neither of which this
  client uses. So no ``crypto_json`` here.
- A streaming reply is ``aibot_respond_msg`` reusing the callback's ``req_id``,
  with ``body.stream = {"id", "content", "finish"}``; every frame carries the
  full text so far and the last frame sets ``finish=true``.

The transport is injected as a ``connect`` callable returning a
:class:`WsConnection`, so the whole dispatch path is exercised by a fake ws in
tests without any network.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Protocol

from integrations.channels.wecom_bot.adapter import WecomBotAdapter
from integrations.channels.wecom_bot.gateway import _MsgidGuard, run_wecom_bot_turn


logger = logging.getLogger(__name__)

DEFAULT_WS_URL = "wss://openws.work.weixin.qq.com"

# Outbound command names.
CMD_SUBSCRIBE = "aibot_subscribe"
CMD_PING = "ping"
CMD_RESPOND_MSG = "aibot_respond_msg"
# Inbound command names.
CMD_MSG_CALLBACK = "aibot_msg_callback"
CMD_EVENT_CALLBACK = "aibot_event_callback"

DEFAULT_HEARTBEAT_INTERVAL = 30.0
# errcode 6000 = another subscriber already holds this bot's socket.
SUBSCRIBE_CONFLICT_ERRCODE = 6000
_BACKOFF_BASE = 1.0
_BACKOFF_MAX = 30.0


def _gen_req_id() -> str:
    return uuid.uuid4().hex


class WsSubscribeConflict(RuntimeError):
    """Raised when another subscriber already holds this bot's socket."""


class WsConnection(Protocol):
    """Minimal duplex JSON-frame connection (aiohttp ws or a test fake)."""

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
        self._adapter = WecomBotAdapter(channel_instance_id=config.channel_instance_id)

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
        logger.info("wecom bot ws connected; subscribing bot_id=%s…", self._config.bot_id[:8])
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
                except WsSubscribeConflict:
                    raise
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
            {
                "cmd": CMD_SUBSCRIBE,
                "headers": {"req_id": _gen_req_id()},
                "body": {"bot_id": self._config.bot_id, "secret": self._config.secret},
            }
        )

    async def _heartbeat(self, conn: WsConnection, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._heartbeat_interval)
                return
            except asyncio.TimeoutError:
                pass
            try:
                await conn.send_json({"cmd": CMD_PING, "headers": {"req_id": _gen_req_id()}})
            except Exception:  # noqa: BLE001 - the receive loop will observe the close
                return

    async def _dispatch(self, conn: WsConnection, frame: Mapping[str, Any]) -> None:
        errcode = frame.get("errcode")
        cmd = frame.get("cmd")
        if cmd != CMD_MSG_CALLBACK:
            # Subscribe ack / pong / event: log so 联调 can confirm the handshake.
            logger.info("wecom bot ws frame cmd=%s errcode=%s errmsg=%s", cmd, errcode, frame.get("errmsg"))
        if isinstance(errcode, int) and errcode != 0:
            if errcode == SUBSCRIBE_CONFLICT_ERRCODE:
                raise WsSubscribeConflict("aibot_subscribe conflict (errcode 6000)")
            return
        if cmd == CMD_MSG_CALLBACK:
            await self._handle_callback(conn, frame)
        # aibot_event_callback / subscribe-ack / pong carry nothing to answer.

    async def _handle_callback(self, conn: WsConnection, frame: Mapping[str, Any]) -> None:
        headers = frame.get("headers") or {}
        req_id = str(headers.get("req_id") or "")
        body = frame.get("body")
        if not isinstance(body, Mapping):
            return
        trace_id = str(body.get("msgid") or f"wecom-bot-{secrets.token_hex(6)}")
        envelope = self._adapter.normalize_message(dict(body), trace_id=trace_id, now=self._now())
        if envelope is None:
            logger.info("wecom bot inbound ignored (non-text/empty) msgid=%s", trace_id)
            return  # non-text or empty — nothing to stream back
        logger.info(
            "wecom bot inbound msgid=%s from=%s chat=%s text_len=%d",
            trace_id, envelope.from_userid, envelope.chat_type, len(envelope.message.text or ""),
        )
        # We own the reply stream id; reuse the inbound one if the bot supplied it.
        stream_id = envelope.stream_id or f"{req_id or trace_id}:{secrets.token_hex(5)}"
        reply_stream = self._reply_stream(conn, req_id=req_id, stream_id=stream_id)
        result = await run_wecom_bot_turn(
            self._sessionmaker,
            channel=self._adapter.channel,
            channel_instance_id=self._config.channel_instance_id,
            envelope=envelope,
            provider=self._provider,
            reply_stream=reply_stream,
            now=self._now(),
            guard=self._guard,
        )
        logger.info("wecom bot turn result msgid=%s status=%s", trace_id, result.get("status"))

    def _reply_stream(
        self, conn: WsConnection, *, req_id: str, stream_id: str
    ) -> Callable[..., Awaitable[None]]:
        async def reply_stream(content: str, *, is_final: bool) -> None:
            logger.info("wecom bot reply stream_id=%s finish=%s len=%d", stream_id, is_final, len(content))
            await conn.send_json(
                {
                    "cmd": CMD_RESPOND_MSG,
                    "headers": {"req_id": req_id},
                    "body": {
                        "msgtype": "stream",
                        "stream": {"id": stream_id, "content": content, "finish": bool(is_final)},
                    },
                }
            )

        return reply_stream
