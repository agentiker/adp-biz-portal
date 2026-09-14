from __future__ import annotations

import os
import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from core.delivery import DeliveryWorker, InboundMessageInput, record_inbound_message
from core.platform import utc_now
from core.platform_worker import PLATFORM_INBOUND_TASK_TYPE, PLATFORM_REPLY_TASK_TYPE, build_platform_delivery_handlers
from integrations.m3.adapter import M3LookupAdapter
from model.account import Account, AccountRole, AccountStatus
from model.platform import (
    PlatformAuditEvent, PlatformAuthSession, PlatformConversation, PlatformDeliveryTask, PlatformEnterprise,
    PlatformEvidence, PlatformExecutionContext, PlatformExecutionRun, PlatformInboundMessage,
    PlatformMembership, PlatformMessage, PlatformToolCall, PlatformToolDefinition, PlatformUser,
    PlatformRole, PlatformStatus,
)

pytestmark = pytest.mark.integration


def _url():
    value = os.getenv("PLATFORM_TEST_DATABASE_URL")
    if not value:
        pytest.skip("设置 PLATFORM_TEST_DATABASE_URL 后运行 PostgreSQL 集成测试")
    return value


@pytest_asyncio.fixture
async def factory():
    database_url = _url()
    schema = f"web_channel_e2e_{uuid.uuid4().hex}"
    admin_engine = create_async_engine(database_url, pool_pre_ping=True)
    async with admin_engine.begin() as conn:
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    await admin_engine.dispose()
    engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": f'"{schema}",public'}},
    )
    tables = [Account.__table__, PlatformEnterprise.__table__, PlatformUser.__table__, PlatformMembership.__table__, PlatformAuthSession.__table__, PlatformConversation.__table__, PlatformExecutionRun.__table__, PlatformEvidence.__table__, PlatformMessage.__table__, PlatformInboundMessage.__table__, PlatformDeliveryTask.__table__, PlatformToolDefinition.__table__, PlatformExecutionContext.__table__, PlatformToolCall.__table__, PlatformAuditEvent.__table__]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Account.metadata.create_all(c, tables=tables, checkfirst=False))
    maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield maker
    finally:
        await engine.dispose()
        cleanup_engine = create_async_engine(database_url, pool_pre_ping=True)
        async with cleanup_engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await cleanup_engine.dispose()


@pytest.mark.asyncio
async def test_web_message_runs_to_portal_reply_once(factory):
    account_id, user_id, enterprise_id, session_id = [uuid.uuid4() for _ in range(4)]
    async with factory() as db:
        db.add_all([
            Account(Id=account_id, Name="E2E", Role=AccountRole.NORMAL, Status=AccountStatus.ACTIVE),
            PlatformEnterprise(Id=enterprise_id, Name="E2E Enterprise", CustomerCode="E2E-001"),
            PlatformToolDefinition(Name="shipment.lookup", Version="1.0", Permission="shipment.read", Enabled=True, ReadOnly=True),
            PlatformUser(Id=user_id, AccountId=account_id, Name="E2E User", PhoneNormalized="13800000001", PhoneMasked="138****0001", Role=PlatformRole.CUSTOMER, Status=PlatformStatus.ACTIVE),
            PlatformAuthSession(Id=session_id, AccountId=account_id, TokenId=uuid.uuid4().hex, ExpiresAt=utc_now() + timedelta(hours=1)),
        ])
        await db.flush()
        db.add(PlatformMembership(UserId=user_id, EnterpriseId=enterprise_id, MembershipRole=PlatformRole.CUSTOMER, Active=True))
        await db.flush()
        message_id = "browser-retry-001"
        kwargs = dict(channel_instance_id="web-portal", external_message_id=message_id, external_conversation_id=f"session:{session_id}", sender_identity_id=str(user_id), text="BL-E2E-001", trace_id="trace-e2e")
        inbound, task, created = await record_inbound_message(db, message=InboundMessageInput(**kwargs), task_type=PLATFORM_INBOUND_TASK_TYPE, task_payload={"platformUserId": str(user_id), "platformSessionId": str(session_id), "enterpriseId": str(enterprise_id), "channel": "web"})
        duplicate, duplicate_task, duplicate_created = await record_inbound_message(db, message=InboundMessageInput(**kwargs), task_type=PLATFORM_INBOUND_TASK_TYPE, task_payload={},)
        await db.commit()
    assert created is True and duplicate_created is False and duplicate.Id == inbound.Id and duplicate_task is None
    worker = DeliveryWorker(sessionmaker=factory, handlers=build_platform_delivery_handlers(factory, adapter_factory=M3LookupAdapter(use_mock=True)), worker_id="web-e2e")
    assert await worker.run_once() is True
    assert await worker.run_once() is True
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(PlatformInboundMessage)) == 1
        assert await db.scalar(select(func.count()).select_from(PlatformExecutionRun)) == 1
        assert await db.scalar(select(func.count()).select_from(PlatformDeliveryTask).where(PlatformDeliveryTask.TaskType == PLATFORM_REPLY_TASK_TYPE)) == 1
        run = (await db.execute(select(PlatformExecutionRun))).scalar_one()
        assert run.Status == "found"
        assert await db.scalar(select(func.count()).select_from(PlatformEvidence)) > 0
        assert await db.scalar(select(func.count()).select_from(PlatformMessage)) == 2
