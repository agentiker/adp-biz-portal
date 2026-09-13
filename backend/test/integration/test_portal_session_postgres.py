from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from core.error.platform import PlatformNotFound
from core.platform import PlatformContext
from integrations.m3.adapter import M3LookupAdapter
from model.account import Account, AccountRole, AccountStatus
from model.platform import (
    PlatformAuditEvent,
    PlatformAuthSession,
    PlatformConversation,
    PlatformCredential,
    PlatformEnterprise,
    PlatformEvidence,
    PlatformExecutionRun,
    PlatformMembership,
    PlatformMessage,
    PlatformRole,
    PlatformStatus,
    PlatformUser,
)


pytestmark = pytest.mark.integration


def _database_url() -> str:
    url = os.getenv("PLATFORM_TEST_DATABASE_URL")
    if not url:
        pytest.skip("设置 PLATFORM_TEST_DATABASE_URL 后运行 PostgreSQL 集成测试")
    return url


@pytest_asyncio.fixture
async def portal_sessionmaker():
    database_url = _database_url()
    schema = f"platform_portal_test_{uuid.uuid4().hex}"
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
        PlatformUser.__table__,
        PlatformMembership.__table__,
        PlatformCredential.__table__,
        PlatformAuthSession.__table__,
        PlatformConversation.__table__,
        PlatformExecutionRun.__table__,
        PlatformMessage.__table__,
        PlatformEvidence.__table__,
        PlatformAuditEvent.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Account.metadata.create_all(
                sync_connection,
                tables=tables,
                checkfirst=False,
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


async def _seed_accounts(factory):
    enterprise_id = uuid.uuid4()
    account_a_id = uuid.uuid4()
    account_b_id = uuid.uuid4()
    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()
    enterprise = PlatformEnterprise(
        Id=enterprise_id,
        Name="Portal 隔离企业",
        CustomerCode=f"PORTAL-{uuid.uuid4().hex[:8]}",
    )
    account_a = Account(Id=account_a_id, Name="Portal 用户 A", Role=AccountRole.NORMAL, Status=AccountStatus.ACTIVE)
    account_b = Account(Id=account_b_id, Name="Portal 用户 B", Role=AccountRole.NORMAL, Status=AccountStatus.ACTIVE)
    user_a = PlatformUser(
        Id=user_a_id,
        AccountId=account_a_id,
        Name="Portal 用户 A",
        PhoneNormalized="13800000001",
        PhoneMasked="138****0001",
        Role=PlatformRole.CUSTOMER,
        Status=PlatformStatus.ACTIVE,
    )
    user_b = PlatformUser(
        Id=user_b_id,
        AccountId=account_b_id,
        Name="Portal 用户 B",
        PhoneNormalized="13800000002",
        PhoneMasked="138****0002",
        Role=PlatformRole.CUSTOMER,
        Status=PlatformStatus.ACTIVE,
    )
    async with factory() as db:
        db.add_all([
            enterprise,
            account_a,
            account_b,
            user_a,
            user_b,
        ])
        await db.flush()
        db.add_all([
            PlatformMembership(
                UserId=user_a_id,
                EnterpriseId=enterprise_id,
                MembershipRole=PlatformRole.CUSTOMER,
                Active=True,
            ),
            PlatformMembership(
                UserId=user_b_id,
                EnterpriseId=enterprise_id,
                MembershipRole=PlatformRole.CUSTOMER,
                Active=True,
            ),
        ])
        await db.commit()
    contexts = {
        "token-a": PlatformContext(
            user=user_a,
            account=account_a,
            session=SimpleNamespace(),
            permissions=frozenset({"shipment.read"}),
        ),
        "token-b": PlatformContext(
            user=user_b,
            account=account_b,
            session=SimpleNamespace(),
            permissions=frozenset({"shipment.read"}),
        ),
    }
    return contexts, enterprise_id


def _request(db, token: str, body: dict | None = None):
    return SimpleNamespace(
        ctx=SimpleNamespace(db=db),
        headers={"Authorization": f"Bearer {token}", "X-Request-Id": f"trace-{token}"},
        cookies={},
        json=body,
    )


def _response_body(response):
    return json.loads(response.body.decode("utf-8"))


@pytest.mark.asyncio
async def test_portal_persists_history_and_keeps_same_enterprise_users_isolated(
    portal_sessionmaker,
    monkeypatch,
):
    from test.app_bootstrap import ensure_app

    ensure_app()
    import router.platform as platform_router

    contexts, enterprise_id = await _seed_accounts(portal_sessionmaker)

    async def fake_load_platform_context(_db, token):
        return contexts[token]

    monkeypatch.setattr(platform_router, "load_platform_context", fake_load_platform_context)
    monkeypatch.setattr(platform_router, "_m3_adapter", lambda: M3LookupAdapter(use_mock=True))

    async with portal_sessionmaker() as db:
        first = _response_body(
            await platform_router.ShipmentLookupApi().post(
                _request(db, "token-a", {"query": "BL-PORTAL-001"})
            )
        )
        conversation_id = first["conversationId"]
        second = _response_body(
            await platform_router.ShipmentLookupApi().post(
                _request(db, "token-a", {"query": "BL-PORTAL-002", "conversationId": conversation_id})
            )
        )
        assert second["conversationId"] == conversation_id

    async with portal_sessionmaker() as db:
        sessions = _response_body(await platform_router.PortalSessionsApi().get(_request(db, "token-a")))
        assert len(sessions) == 1
        assert sessions[0]["id"] == conversation_id
        assert sessions[0]["query"] == "BL-PORTAL-002"
        assert sessions[0]["evidence"] is True

        detail = _response_body(
            await platform_router.PortalSessionDetailApi().get(
                _request(db, "token-a"), conversation_id
            )
        )
        assert detail["conversation"]["id"] == conversation_id
        assert detail["result"]["query"] == "BL-PORTAL-002"
        assert len(detail["messages"]) == 4
        assert [message["direction"] for message in detail["messages"]] == [
            "inbound",
            "assistant",
            "inbound",
            "assistant",
        ]
        assert len(detail["runs"]) == 2
        assert detail["runs"][-1]["evidence"]
        assert detail["result"]["evidence"] == detail["runs"][-1]["evidence"]

    async with portal_sessionmaker() as db:
        with pytest.raises(PlatformNotFound, match="会话不存在或无权访问"):
            await platform_router.PortalSessionDetailApi().get(
                _request(db, "token-b"), conversation_id
            )

    output = Path(__file__).resolve().parents[3] / "output" / "tests" / "m2-web-01-portal.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "scope": "M2-WEB-01 portal session persistence and isolation",
                "conversationId": conversation_id,
                "sameEnterpriseCrossAccountRead": False,
                "messagesRestored": 4,
                "executionRunsRestored": 2,
                "latestResultQuery": "BL-PORTAL-002",
                "evidenceRestored": True,
                "enterpriseId": str(enterprise_id),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
