"""WeChat 客服 cursor pull: every page dispatched, cursor advances, msgid dedup."""

from __future__ import annotations

import base64
import os
import uuid
from typing import Any, Mapping

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from core.channel_cursor import get_cursor
from core.channel_pull import sync_wechat_kf
from integrations.channels.wechat_kf.adapter import WechatKfAdapter
from model.account import Account, AccountRole, AccountStatus
from model.platform import (
    PlatformAuditEvent,
    PlatformChannelCursor,
    PlatformChannelIdentity,
    PlatformChannelIdentityStatus,
    PlatformDeliveryTask,
    PlatformEnterprise,
    PlatformInboundMessage,
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
async def kf_sessionmaker():
    database_url = _database_url()
    schema = f"platform_kf_test_{uuid.uuid4().hex}"
    admin_engine = create_async_engine(database_url, pool_pre_ping=True)
    async with admin_engine.begin() as connection:
        await connection.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    await admin_engine.dispose()
    engine = create_async_engine(
        database_url, pool_size=4, max_overflow=0, pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": f'"{schema}",public'}},
    )
    tables = [
        Account.__table__, PlatformEnterprise.__table__, PlatformUser.__table__,
        PlatformChannelIdentity.__table__,
        PlatformChannelCursor.__table__, PlatformInboundMessage.__table__,
        PlatformDeliveryTask.__table__, PlatformAuditEvent.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda c: Account.metadata.create_all(c, tables=tables, checkfirst=False))
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()
        cleanup = create_async_engine(database_url, pool_pre_ping=True)
        async with cleanup.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await cleanup.dispose()


class _FakeTransport:
    """Serves a scripted list of sync_msg pages, ignoring the cursor."""

    def __init__(self, pages: list[Mapping[str, Any]]):
        self._pages = list(pages)
        self.calls: list[tuple[str, str | None]] = []

    async def sync_msg(self, *, cursor: str, open_kfid: str, callback_token: str | None) -> Mapping[str, Any]:
        self.calls.append((cursor, callback_token))
        if self._pages:
            return self._pages.pop(0)
        return {"errcode": 0, "next_cursor": cursor or "end", "has_more": 0, "msg_list": []}


def _item(msgid: str, content: str) -> dict[str, Any]:
    return {
        "msgid": msgid, "open_kfid": "wkAAA", "external_userid": "wmUser",
        "origin": 3, "msgtype": "text", "text": {"content": content}, "send_time": 1_700_000_000,
    }


async def _seed_bound_identity(factory) -> None:
    account_id = uuid.uuid4()
    user_id = uuid.uuid4()
    async with factory() as db:
        db.add(Account(Id=account_id, Name="KF 用户", Role=AccountRole.NORMAL, Status=AccountStatus.ACTIVE))
        db.add(PlatformUser(
            Id=user_id, AccountId=account_id, Name="KF 用户",
            PhoneNormalized="13800009999", PhoneMasked="138****9999",
            Role=PlatformRole.CUSTOMER, Status=PlatformStatus.ACTIVE,
        ))
        await db.flush()
        db.add(PlatformChannelIdentity(
            UserId=user_id, AccountId=account_id, EnterpriseId=None,
            Channel="wechat_kf", ChannelInstanceId="kf-1", ExternalIdentityId="wmUser",
            Status=PlatformChannelIdentityStatus.ACTIVE,
        ))
        await db.commit()


def _adapter() -> WechatKfAdapter:
    return WechatKfAdapter(channel_instance_id="kf-1", corp_id="corp-1", token="tok", encoding_aes_key=AES_KEY_B64)


@pytest.mark.asyncio
async def test_pull_dispatches_every_page_and_advances_cursor(kf_sessionmaker):
    await _seed_bound_identity(kf_sessionmaker)
    transport = _FakeTransport([
        {"errcode": 0, "next_cursor": "c1", "has_more": 1, "msg_list": [_item("mA", "BL-A")]},
        {"errcode": 0, "next_cursor": "c2", "has_more": 0, "msg_list": [_item("mB", "BL-B")]},
    ])
    async with kf_sessionmaker() as db:
        stats = await sync_wechat_kf(
            db, adapter=_adapter(), transport=transport, open_kfid="wkAAA",
            callback_token="pull-token", trace_id="kf-trace",
        )
    assert stats == {"pages": 2, "seen": 2, "enqueued": 2}
    # Both pages dispatched (not just the last — the reference bug).
    async with kf_sessionmaker() as db:
        ids = set((await db.execute(select(PlatformInboundMessage.ExternalMessageId))).scalars().all())
        assert ids == {"mA", "mB"}
        cursor = await get_cursor(db, channel="wechat_kf", channel_instance_id="kf-1", scope_id="wkAAA")
        assert cursor == "c2"
    # First page sent the callback token (no cursor); later pages did not.
    assert transport.calls[0] == ("", "pull-token")
    assert transport.calls[1] == ("c1", None)


@pytest.mark.asyncio
async def test_pull_is_idempotent_on_replayed_msgids(kf_sessionmaker):
    await _seed_bound_identity(kf_sessionmaker)
    pages = [{"errcode": 0, "next_cursor": "c1", "has_more": 0, "msg_list": [_item("mA", "BL-A")]}]
    async with kf_sessionmaker() as db:
        await sync_wechat_kf(
            db, adapter=_adapter(), transport=_FakeTransport(list(pages)), open_kfid="wkAAA",
            callback_token="t", trace_id="kf-trace",
        )
    # Replay the same msgid → deduped, no second inbound row.
    async with kf_sessionmaker() as db:
        stats = await sync_wechat_kf(
            db, adapter=_adapter(), transport=_FakeTransport(list(pages)), open_kfid="wkAAA",
            callback_token="t", trace_id="kf-trace",
        )
        assert stats["enqueued"] == 0
        count = (await db.execute(select(func.count()).select_from(PlatformInboundMessage))).scalar_one()
        assert count == 1


@pytest.mark.asyncio
async def test_prime_drains_without_dispatching(kf_sessionmaker):
    await _seed_bound_identity(kf_sessionmaker)
    transport = _FakeTransport([
        {"errcode": 0, "next_cursor": "c1", "has_more": 0, "msg_list": [_item("mA", "BL-A")]},
    ])
    async with kf_sessionmaker() as db:
        stats = await sync_wechat_kf(
            db, adapter=_adapter(), transport=transport, open_kfid="wkAAA",
            callback_token="t", trace_id="kf-trace", dispatch=False,
        )
    assert stats["enqueued"] == 0
    async with kf_sessionmaker() as db:
        count = (await db.execute(select(func.count()).select_from(PlatformInboundMessage))).scalar_one()
        assert count == 0  # backlog drained, nothing dispatched
        assert await get_cursor(db, channel="wechat_kf", channel_instance_id="kf-1", scope_id="wkAAA") == "c1"
