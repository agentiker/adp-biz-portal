"""Public no-login shared-result endpoint: read one result, then revoke it."""

from __future__ import annotations

import json
import os
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from core.channel_share import (
    create_shared_result,
    revoke_account_shared_results,
    shared_result_token_hash,
)
from core.error.platform import PlatformNotFound
from model.account import Account, AccountRole, AccountStatus
from model.platform import (
    PlatformAuditEvent,
    PlatformConversation,
    PlatformEnterprise,
    PlatformEvidence,
    PlatformExecutionRun,
    PlatformSharedResult,
)


def _database_url() -> str:
    url = os.environ.get("PLATFORM_TEST_DATABASE_URL")
    if not url:
        pytest.skip("设置 PLATFORM_TEST_DATABASE_URL 后运行 PostgreSQL 集成测试")
    return url


@pytest_asyncio.fixture
async def shared_sessionmaker():
    database_url = _database_url()
    schema = f"platform_shared_test_{uuid.uuid4().hex}"
    admin_engine = create_async_engine(database_url, pool_pre_ping=True)
    async with admin_engine.begin() as connection:
        await connection.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    await admin_engine.dispose()

    engine = create_async_engine(
        database_url,
        pool_size=4,
        max_overflow=0,
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": f'"{schema}",public'}},
    )
    tables = [
        Account.__table__,
        PlatformEnterprise.__table__,
        PlatformConversation.__table__,
        PlatformExecutionRun.__table__,
        PlatformEvidence.__table__,
        PlatformSharedResult.__table__,
        PlatformAuditEvent.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Account.metadata.create_all(
                sync_connection, tables=tables, checkfirst=False
            )
        )
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()
        cleanup_engine = create_async_engine(database_url, pool_pre_ping=True)
        async with cleanup_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await cleanup_engine.dispose()


def _request(db):
    return SimpleNamespace(
        ctx=SimpleNamespace(db=db),
        headers={"X-Request-Id": "trace-shared"},
        cookies={},
        json=None,
    )


async def _seed_run(factory) -> tuple[str, str]:
    enterprise_id = uuid.uuid4()
    account_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    run_id = uuid.uuid4()
    async with factory() as db:
        db.add_all([
            PlatformEnterprise(Id=enterprise_id, Name="Shared 企业", CustomerCode=f"S-{uuid.uuid4().hex[:8]}"),
            Account(Id=account_id, Name="Shared 用户", Role=AccountRole.NORMAL, Status=AccountStatus.ACTIVE),
        ])
        await db.flush()
        db.add(PlatformConversation(
            Id=conversation_id, AccountId=account_id, EnterpriseId=enterprise_id,
            Channel="wechat_official_account", Title="业务查询",
        ))
        db.add(PlatformExecutionRun(
            Id=run_id, ConversationId=conversation_id, AccountId=account_id, EnterpriseId=enterprise_id,
            RunId=f"run_{uuid.uuid4().hex}", Query="BL-SHARED-001", Status="success",
            Title="提单 BL-SHARED-001", Summary="货物已到港，可安排提货。" * 20, TraceId="trace-shared",
        ))
        await db.flush()
        db.add(PlatformEvidence(
            ExecutionRunId=run_id, ConversationId=conversation_id, AccountId=account_id, EnterpriseId=enterprise_id,
            Label="状态", Value="已到港", Source="m3", Known=True,
        ))
        await db.commit()
    return str(account_id), str(run_id)


@pytest.mark.asyncio
async def test_shared_result_reads_then_revokes(shared_sessionmaker):
    from test.app_bootstrap import ensure_app

    ensure_app()
    import router.platform as platform_router

    account_id, run_id = await _seed_run(shared_sessionmaker)

    async with shared_sessionmaker() as db:
        token = await create_shared_result(
            db,
            execution_run_id=run_id,
            conversation_id=None,
            account_id=account_id,
            enterprise_id=None,
            channel="wechat_official_account",
            channel_instance_id="oa-1",
        )
        await db.commit()

    # Valid token → read-only result with summary + evidence, no login.
    async with shared_sessionmaker() as db:
        response = await platform_router.PortalSharedResultApi().get(_request(db), token)
    body = json.loads(response.body.decode("utf-8"))
    assert body["result"]["title"] == "提单 BL-SHARED-001"
    assert body["result"]["status"] == "success"
    assert any(item["label"] == "状态" and item["value"] == "已到港" for item in body["result"]["evidence"])

    # Unknown token → 404 (never 401).
    async with shared_sessionmaker() as db:
        with pytest.raises(PlatformNotFound):
            await platform_router.PortalSharedResultApi().get(_request(db), "psr_does-not-exist")

    # Revoke on account disable/unbind → link dies.
    async with shared_sessionmaker() as db:
        await revoke_account_shared_results(db, account_id)
        await db.commit()
    async with shared_sessionmaker() as db:
        with pytest.raises(PlatformNotFound):
            await platform_router.PortalSharedResultApi().get(_request(db), token)


@pytest.mark.asyncio
async def test_shared_result_expires_when_ttl_is_set(shared_sessionmaker):
    """The default link is permanent, but a positive TTL still expires."""
    from datetime import timedelta

    from core.platform import utc_now
    from model.platform import PlatformSharedResult

    from test.app_bootstrap import ensure_app

    ensure_app()
    import router.platform as platform_router

    account_id, run_id = await _seed_run(shared_sessionmaker)

    async with shared_sessionmaker() as db:
        token = await create_shared_result(
            db,
            execution_run_id=run_id,
            conversation_id=None,
            account_id=account_id,
            enterprise_id=None,
            channel="wechat_official_account",
            channel_instance_id="oa-1",
            ttl_seconds=3600,
        )
        await db.commit()

    # Backdate the expiry to the past → the link must stop resolving.
    digest = shared_result_token_hash(token)
    async with shared_sessionmaker() as db:
        row = (await db.execute(
            select(PlatformSharedResult).where(PlatformSharedResult.TokenHash == digest)
        )).scalar_one()
        row.ExpiresAt = utc_now() - timedelta(minutes=1)
        db.add(row)
        await db.commit()

    async with shared_sessionmaker() as db:
        with pytest.raises(PlatformNotFound):
            await platform_router.PortalSharedResultApi().get(_request(db), token)
