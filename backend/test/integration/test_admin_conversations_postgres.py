"""Admin conversation history: cross-enterprise listing, pagination, detail, authz."""

from __future__ import annotations

import json
import os
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from core.error.platform import PlatformForbidden
from core.platform import PlatformContext
from model.account import Account, AccountRole, AccountStatus
from model.platform import (
    EnterpriseStatus,
    PlatformConversation,
    PlatformEnterprise,
    PlatformExecutionRun,
    PlatformMessage,
    PlatformRole,
    PlatformStatus,
    PlatformUser,
)


def _database_url() -> str:
    url = os.environ.get("PLATFORM_TEST_DATABASE_URL")
    if not url:
        pytest.skip("设置 PLATFORM_TEST_DATABASE_URL 后运行 PostgreSQL 集成测试")
    return url


@pytest_asyncio.fixture
async def conv_sessionmaker():
    database_url = _database_url()
    schema = f"platform_conv_test_{uuid.uuid4().hex}"
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
        PlatformConversation.__table__, PlatformExecutionRun.__table__, PlatformMessage.__table__,
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


def _request(db, *, args: dict | None = None):
    return SimpleNamespace(
        ctx=SimpleNamespace(db=db),
        headers={"Authorization": "Bearer admin", "X-Request-Id": "trace-admin"},
        cookies={},
        args=args or {},
        json=None,
    )


def _body(response):
    return json.loads(response.body.decode("utf-8"))


async def _seed(factory):
    admin_account = uuid.uuid4()
    async with factory() as db:
        db.add(Account(Id=admin_account, Name="平台管理员", Role=AccountRole.ADMIN, Status=AccountStatus.ACTIVE))
        await db.flush()
        db.add(PlatformUser(Id=uuid.uuid4(), AccountId=admin_account, Name="平台管理员", PhoneNormalized="13700000000", PhoneMasked="137****0000", Role=PlatformRole.ADMIN, Status=PlatformStatus.ACTIVE))
        conv_ids = []
        for idx in range(2):
            ent_id, acc_id = uuid.uuid4(), uuid.uuid4()
            db.add(PlatformEnterprise(Id=ent_id, Name=f"企业{idx}", CustomerCode=f"C-{idx}-{uuid.uuid4().hex[:6]}", Status=EnterpriseStatus.ACTIVE))
            db.add(Account(Id=acc_id, Name=f"客户{idx}", Role=AccountRole.NORMAL, Status=AccountStatus.ACTIVE))
            await db.flush()
            conv_id = uuid.uuid4()
            conv_ids.append(str(conv_id))
            db.add(PlatformConversation(Id=conv_id, AccountId=acc_id, EnterpriseId=ent_id, Channel="wecom_bot", Title=f"业务查询 / BL-{idx}"))
            run_id = uuid.uuid4()
            db.add(PlatformExecutionRun(Id=run_id, ConversationId=conv_id, AccountId=acc_id, EnterpriseId=ent_id, RunId=f"run-{idx}", Query=f"BL-{idx}", Status="found", Title=f"提单 BL-{idx}", Summary="已到港", TraceId=f"trace-{idx}"))
            db.add(PlatformMessage(Id=uuid.uuid4(), ConversationId=conv_id, AccountId=acc_id, EnterpriseId=ent_id, ExecutionRunId=run_id, Direction="assistant", MessageType="shipment.result", Body="已到港", TraceId=f"trace-{idx}"))
        await db.commit()
    return admin_account, conv_ids


def _admin_context(account_id, *, manage: bool = True):
    return PlatformContext(
        user=SimpleNamespace(Id=uuid.uuid4(), Role=PlatformRole.ADMIN),
        account=SimpleNamespace(Id=account_id),
        session=SimpleNamespace(),
        permissions=frozenset({"platform.manage"} if manage else {"shipment.read"}),
    )


def _install_context(monkeypatch, platform_router, ctx):
    async def _load(_db, _token):
        return ctx
    monkeypatch.setattr(platform_router, "load_platform_context", _load)


@pytest.mark.asyncio
async def test_admin_lists_conversations_across_enterprises(conv_sessionmaker, monkeypatch):
    from test.app_bootstrap import ensure_app
    ensure_app()
    import router.platform as platform_router

    admin_account, conv_ids = await _seed(conv_sessionmaker)
    _install_context(monkeypatch, platform_router, _admin_context(admin_account))

    async with conv_sessionmaker() as db:
        listing = _body(await platform_router.AdminConversationListApi().get(_request(db)))
        assert listing["total"] == 2 and len(listing["items"]) == 2
        # Cross-enterprise: both enterprises appear with names.
        names = {item["enterpriseName"] for item in listing["items"]}
        assert names == {"企业0", "企业1"}
        assert all(item["accountName"] for item in listing["items"])

        detail = _body(await platform_router.AdminConversationDetailApi().get(_request(db), conv_ids[0]))
        assert detail["conversation"]["enterpriseName"] in {"企业0", "企业1"}
        assert len(detail["messages"]) == 1 and detail["messages"][0]["body"] == "已到港"
        assert detail["runs"][0]["status"] == "found"


@pytest.mark.asyncio
async def test_admin_conversations_pagination(conv_sessionmaker, monkeypatch):
    from test.app_bootstrap import ensure_app
    ensure_app()
    import router.platform as platform_router
    admin_account, _ = await _seed(conv_sessionmaker)
    _install_context(monkeypatch, platform_router, _admin_context(admin_account))
    async with conv_sessionmaker() as db:
        page = _body(await platform_router.AdminConversationListApi().get(_request(db, args={"limit": "1", "offset": "0"})))
        assert page["total"] == 2 and len(page["items"]) == 1 and page["limit"] == 1


@pytest.mark.asyncio
async def test_admin_conversations_requires_manage_permission(conv_sessionmaker, monkeypatch):
    from test.app_bootstrap import ensure_app
    ensure_app()
    import router.platform as platform_router
    admin_account, _ = await _seed(conv_sessionmaker)
    _install_context(monkeypatch, platform_router, _admin_context(admin_account, manage=False))
    async with conv_sessionmaker() as db:
        with pytest.raises(PlatformForbidden):
            await platform_router.AdminConversationListApi().get(_request(db))
