"""企微智能机器人 inline streaming turn: cumulative frames, unbound, dedup."""

from __future__ import annotations

import base64
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from integrations.adp.provider import AgentResponse
from integrations.channels.wecom_bot.adapter import WECOM_BOT, WecomBotAdapter
from integrations.channels.wecom_bot.gateway import _MsgidGuard, run_wecom_bot_turn
from integrations.channels.wecom_bot.ws_client import WecomBotWsConfig, WecomBotWsGateway
from model.account import Account, AccountRole, AccountStatus
from model.platform import (
    EnterpriseStatus,
    PlatformChannelIdentity,
    PlatformChannelIdentityStatus,
    PlatformConversation,
    PlatformEnterprise,
    PlatformEvidence,
    PlatformExecutionRun,
    PlatformMembership,
    PlatformMessage,
    PlatformRole,
    PlatformStatus,
    PlatformUser,
)


AES_KEY_B64 = base64.b64encode(bytes(range(32))).decode().rstrip("=")


def _database_url() -> str:
    url = os.environ.get("PLATFORM_TEST_DATABASE_URL")
    if not url:
        pytest.skip("设置 PLATFORM_TEST_DATABASE_URL 后运行 PostgreSQL 集成测试")
    return url


@pytest_asyncio.fixture
async def bot_sessionmaker():
    database_url = _database_url()
    schema = f"platform_bot_test_{uuid.uuid4().hex}"
    admin = create_async_engine(database_url, pool_pre_ping=True)
    async with admin.begin() as c:
        await c.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        await c.execute(text(f'CREATE SCHEMA "{schema}"'))
    await admin.dispose()
    engine = create_async_engine(
        database_url, pool_size=4, max_overflow=0, pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": f'"{schema}",public'}},
    )
    tables = [
        Account.__table__, PlatformEnterprise.__table__, PlatformUser.__table__,
        PlatformMembership.__table__, PlatformChannelIdentity.__table__,
        PlatformConversation.__table__, PlatformExecutionRun.__table__,
        PlatformEvidence.__table__, PlatformMessage.__table__,
    ]
    async with engine.begin() as c:
        await c.run_sync(lambda s: Account.metadata.create_all(s, tables=tables, checkfirst=False))
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()
        cleanup = create_async_engine(database_url, pool_pre_ping=True)
        async with cleanup.begin() as c:
            await c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await cleanup.dispose()


class _Recorder:
    def __init__(self):
        self.frames = []

    async def push(self, content, *, is_final):
        self.frames.append((content, is_final))


class _StreamingProvider:
    capabilities = frozenset({"shipment.lookup"})
    agent_id = "app-123"

    async def execute(self, request, *, sink=None):
        if sink is not None:
            await sink.emit("正在核对")
            await sink.emit("提单。")
            await sink.emit("已到港。")
        return AgentResponse(
            status="found", query=request.query, title="提单 BL-1",
            summary="正在核对提单。已到港。",
            evidence=[{"label": "状态", "value": "已到港", "source": "m3", "known": True}],
            provider_trace_id="tr", audit_outcome="success",
        )


async def _seed_identity(factory, *, bind: bool) -> None:
    account_id, user_id, ent_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with factory() as db:
        db.add(PlatformEnterprise(Id=ent_id, Name="Bot 企业", CustomerCode=f"B-{uuid.uuid4().hex[:8]}", Status=EnterpriseStatus.ACTIVE))
        db.add(Account(Id=account_id, Name="Bot 用户", Role=AccountRole.NORMAL, Status=AccountStatus.ACTIVE))
        db.add(PlatformUser(Id=user_id, AccountId=account_id, Name="Bot 用户", PhoneNormalized="13800008888", PhoneMasked="138****8888", Role=PlatformRole.CUSTOMER, Status=PlatformStatus.ACTIVE))
        await db.flush()
        db.add(PlatformMembership(UserId=user_id, EnterpriseId=ent_id, MembershipRole=PlatformRole.CUSTOMER, Active=True))
        if bind:
            db.add(PlatformChannelIdentity(
                UserId=user_id, AccountId=account_id, EnterpriseId=None,
                Channel=WECOM_BOT, ChannelInstanceId="bot-1", ExternalIdentityId="u1",
                Status=PlatformChannelIdentityStatus.ACTIVE,
            ))
        await db.commit()


def _envelope():
    adapter = WecomBotAdapter(channel_instance_id="bot-1", corp_id="corp-1", token="tok", encoding_aes_key=AES_KEY_B64)
    return adapter.normalize_message(
        {"msgtype": "text", "msgid": "m1", "chattype": "single", "from": {"userid": "u1"}, "text": {"content": "BL-1"}, "stream": {"id": "s1"}},
        trace_id="bot-trace",
    )


@pytest.mark.asyncio
async def test_bound_message_streams_cumulative_frames_and_records(bot_sessionmaker):
    await _seed_identity(bot_sessionmaker, bind=True)
    rec = _Recorder()
    result = await run_wecom_bot_turn(
        bot_sessionmaker, channel=WECOM_BOT, channel_instance_id="bot-1", envelope=_envelope(),
        provider=_StreamingProvider(), reply_stream=rec.push, guard=_MsgidGuard(),
    )
    assert result["status"] == "streamed"
    # Loading frame first, then cumulative snapshots, then a final frame.
    assert rec.frames[0] == ("", False)
    assert rec.frames[-1][1] is True
    contents = [c for c, _ in rec.frames if c]
    assert contents == sorted(contents, key=len)  # monotonically growing (cumulative)
    assert "已到港" in rec.frames[-1][0]
    async with bot_sessionmaker() as db:
        runs = (await db.execute(select(func.count()).select_from(PlatformExecutionRun))).scalar_one()
        msgs = (await db.execute(select(func.count()).select_from(PlatformMessage))).scalar_one()
        assert runs == 1 and msgs == 1


@pytest.mark.asyncio
async def test_unbound_sender_gets_guidance_frame(bot_sessionmaker):
    await _seed_identity(bot_sessionmaker, bind=False)
    rec = _Recorder()
    result = await run_wecom_bot_turn(
        bot_sessionmaker, channel=WECOM_BOT, channel_instance_id="bot-1", envelope=_envelope(),
        provider=_StreamingProvider(), reply_stream=rec.push, guard=_MsgidGuard(),
    )
    assert result["status"] == "unbound"
    assert len(rec.frames) == 1
    content, is_final = rec.frames[0]
    assert is_final is True and "绑定" in content


@pytest.mark.asyncio
async def test_duplicate_msgid_is_dropped(bot_sessionmaker):
    await _seed_identity(bot_sessionmaker, bind=True)
    guard = _MsgidGuard()
    rec1 = _Recorder()
    await run_wecom_bot_turn(
        bot_sessionmaker, channel=WECOM_BOT, channel_instance_id="bot-1", envelope=_envelope(),
        provider=_StreamingProvider(), reply_stream=rec1.push, guard=guard,
    )
    rec2 = _Recorder()
    result = await run_wecom_bot_turn(
        bot_sessionmaker, channel=WECOM_BOT, channel_instance_id="bot-1", envelope=_envelope(),
        provider=_StreamingProvider(), reply_stream=rec2.push, guard=guard,
    )
    assert result["status"] == "duplicate"
    assert rec2.frames == []


class _FakeWs:
    def __init__(self, inbound):
        self.inbound = list(inbound)
        self.sent = []

    async def send_json(self, data):
        self.sent.append(dict(data))

    async def receive_json(self):
        return self.inbound.pop(0) if self.inbound else None

    async def close(self):
        pass


def _callback_frame(msg: dict) -> dict:
    """A plaintext aibot_msg_callback frame (WS long-connection carries no crypto)."""
    return {"cmd": "aibot_msg_callback", "headers": {"req_id": "r1"}, "body": msg}


@pytest.mark.asyncio
async def test_ws_gateway_subscribes_and_streams_replies(bot_sessionmaker):
    await _seed_identity(bot_sessionmaker, bind=True)
    frame = _callback_frame(
        {"msgtype": "text", "msgid": "wm1", "chattype": "single",
         "from": {"userid": "u1"}, "text": {"content": "BL-1"}, "stream": {"id": "s9"}}
    )
    ws = _FakeWs([frame])

    async def _connect():
        return ws

    config = WecomBotWsConfig(channel_instance_id="bot-1", bot_id="b-1", secret="sec")
    gw = WecomBotWsGateway(
        config=config, provider=_StreamingProvider(), sessionmaker=bot_sessionmaker,
        connect=_connect, guard=_MsgidGuard(), now=lambda: 1700000000.0,
    )
    await gw.serve_once()

    # The session opens with an aibot_subscribe carrying bot_id + secret.
    assert ws.sent[0]["cmd"] == "aibot_subscribe"
    assert ws.sent[0]["body"] == {"bot_id": "b-1", "secret": "sec"}
    assert "req_id" in ws.sent[0]["headers"]

    replies = [f for f in ws.sent if f.get("cmd") == "aibot_respond_msg"]
    assert replies, ws.sent
    contents, finals = [], []
    for f in replies:
        assert f["headers"]["req_id"] == "r1"  # reuse the callback's req_id
        stream = f["body"]["stream"]
        assert f["body"]["msgtype"] == "stream" and stream["id"] == "s9"
        contents.append(stream["content"])
        finals.append(stream["finish"])
    # Cumulative snapshots (growing text), last frame marks the bubble finished.
    assert finals[-1] is True
    nonempty = [c for c in contents if c]
    assert nonempty == sorted(nonempty, key=len)
    assert "已到港" in contents[-1]


@pytest.mark.asyncio
async def test_ws_gateway_ignores_event_callback(bot_sessionmaker):
    await _seed_identity(bot_sessionmaker, bind=True)
    frame = {"cmd": "aibot_event_callback", "headers": {"req_id": "r2"},
             "body": {"event": {"eventtype": "enter_chat"}}}
    ws = _FakeWs([frame])

    async def _connect():
        return ws

    config = WecomBotWsConfig(channel_instance_id="bot-1", bot_id="b-1", secret="sec")
    gw = WecomBotWsGateway(
        config=config, provider=_StreamingProvider(), sessionmaker=bot_sessionmaker,
        connect=_connect, guard=_MsgidGuard(), now=lambda: 1700000000.0,
    )
    await gw.serve_once()
    assert [f for f in ws.sent if f.get("cmd") == "aibot_respond_msg"] == []
