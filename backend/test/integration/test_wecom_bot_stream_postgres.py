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
    PlatformAdpApp, PlatformAdpApiKey,
    PlatformExecutionContext, PlatformToolCall, PlatformToolDefinition,
    PlatformAuthSession, PlatformAuditEvent,
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
        Account.__table__, PlatformAdpApp.__table__, PlatformAdpApiKey.__table__, PlatformEnterprise.__table__, PlatformUser.__table__,
        PlatformMembership.__table__, PlatformChannelIdentity.__table__,
        PlatformConversation.__table__, PlatformExecutionRun.__table__,
        PlatformEvidence.__table__, PlatformMessage.__table__,
        PlatformAuthSession.__table__, PlatformExecutionContext.__table__,
        PlatformToolDefinition.__table__, PlatformToolCall.__table__, PlatformAuditEvent.__table__,
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
    # Native 思考中 placeholder first, then cumulative snapshots, then a final frame.
    assert rec.frames[0] == ("<think></think>", False)
    assert rec.frames[-1][1] is True
    contents = [c for c, _ in rec.frames if c and c != "<think></think>"]
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


class _ThinkingProvider:
    capabilities = frozenset({"shipment.lookup"})
    agent_id = "app-123"

    async def execute(self, request, *, sink=None):
        if sink is not None:
            await sink.emit_reasoning("先核对提单号")   # reasoning first (thought message)
            await sink.emit_reasoning("，查询到港状态")
            await sink.emit("提单 BL-1 已到港。")        # then the answer (reply message)
        return AgentResponse(
            status="found", query=request.query, title="提单 BL-1",
            summary="提单 BL-1 已到港。",
            evidence=[{"label": "状态", "value": "已到港", "source": "m3", "known": True}],
            provider_trace_id="tr", audit_outcome="success",
        )


@pytest.mark.asyncio
async def test_reasoning_folds_into_think_block_before_answer(bot_sessionmaker):
    await _seed_identity(bot_sessionmaker, bind=True)
    rec = _Recorder()
    result = await run_wecom_bot_turn(
        bot_sessionmaker, channel=WECOM_BOT, channel_instance_id="bot-1", envelope=_envelope(),
        provider=_ThinkingProvider(), reply_stream=rec.push, guard=_MsgidGuard(),
    )
    assert result["status"] == "streamed"
    finals = [c for c, is_final in rec.frames if is_final]
    final = finals[-1]
    # Thinking is folded in a <think> block; the answer follows and is clean.
    assert final.startswith("<think>") and "</think>" in final
    assert "先核对提单号" in final and "查询到港状态" in final
    answer_part = final.split("</think>", 1)[1]
    assert "已到港" in answer_part and "<think>" not in answer_part
    # The stored answer (DB/summary) must not contain the reasoning.
    async with bot_sessionmaker() as db:
        msg = (await db.execute(select(PlatformMessage))).scalars().first()
        assert "先核对提单号" not in (msg.Body or "") and "已到港" in (msg.Body or "")


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
    nonempty = [c for c in contents if c and c != "<think></think>"]
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


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["found", "no_callback", "revoked"])
async def test_adp_bot_uses_recorded_callback_evidence(bot_sessionmaker, monkeypatch, mode):
    from types import SimpleNamespace
    from core.platform import AccountUnauthorized
    with_callback = mode != "no_callback"
    from integrations.adp.provider import ADPAgentProvider
    from core.platform import ensure_platform_tools
    from config import tagentic_config
    from test.app_bootstrap import ensure_app
    ensure_app()
    from router.platform import AdpShipmentLookupApi

    from cryptography.fernet import Fernet
    from config import tagentic_config
    monkeypatch.setattr(tagentic_config, "PLATFORM_CHANNEL_CREDENTIAL_KEY", Fernet.generate_key().decode())
    await _seed_identity(bot_sessionmaker, bind=True)
    from core.adp_api_key import create_api_key
    async with bot_sessionmaker() as key_db:
        _, connector_key = await create_api_key(key_db, "test connector")
        await key_db.commit()
    monkeypatch.setattr(tagentic_config, "M3_USE_MOCK", True)
    async with bot_sessionmaker() as db:
        enterprise = (await db.execute(select(PlatformEnterprise))).scalar_one()
        enterprise.CustomerCode = "MOCK-ENT-A"
        await ensure_platform_tools(db)
        await db.commit()
    rec = _Recorder()
    tokens = []

    class Vendor:
        async def chat(self, **kwargs):
            variables = kwargs["custom_variables"]
            tokens.append(variables["platform_context_token"])
            if with_callback:
                async with bot_sessionmaker() as callback_db:
                    request = SimpleNamespace(
                        ctx=SimpleNamespace(db=callback_db),
                        headers={"X-ADP-Service-Token": connector_key,
                                 "X-Platform-Context-Token": tokens[-1],
                                 "X-ADP-Request-Id": variables["platform_tool_request_id"] + ":lookup"},
                        json={"query": "MOCK-BL-A001"},
                    )
                    response = await AdpShipmentLookupApi().post(request)
                    assert response.status == 200
            if mode == "revoked":
                async with bot_sessionmaker() as revoke_db:
                    user = (await revoke_db.execute(select(PlatformUser))).scalar_one()
                    user.Status = PlatformStatus.DISABLED
                    await revoke_db.commit()
            yield b'data: {"Type":"text.delta","Text":"FABRICATED ARRIVAL"}\n\n'

    turn = run_wecom_bot_turn(
        bot_sessionmaker, channel=WECOM_BOT, channel_instance_id="bot-1", envelope=_envelope(),
        provider=ADPAgentProvider(agent_id="test-agent", application_id="test-app", vendor=Vendor()),
        reply_stream=rec.push, guard=_MsgidGuard(),
    )
    if mode == "revoked":
        with pytest.raises(AccountUnauthorized):
            await turn
        assert rec.frames == [("<think></think>", False)]
        async with bot_sessionmaker() as db:
            contexts = list((await db.execute(select(PlatformExecutionContext))).scalars())
            assert len(contexts) == 1 and contexts[0].RevokedAt is not None
        return
    result = await turn
    assert result["status"] == "streamed"
    assert rec.frames[-1][1] is True
    assert all("FABRICATED" not in content and tokens[0] not in content for content, _ in rec.frames)
    async with bot_sessionmaker() as db:
        run = (await db.execute(select(PlatformExecutionRun))).scalar_one()
        assert run.Status == ("found" if with_callback else "upstream_error")
        message = (await db.execute(select(PlatformMessage))).scalar_one()
        assert message.Body in rec.frames[-1][0]
        assert ("ALPHA" in message.Body) is with_callback
        contexts = list((await db.execute(select(PlatformExecutionContext))).scalars())
        assert len(contexts) == 1 and contexts[0].RevokedAt is not None
