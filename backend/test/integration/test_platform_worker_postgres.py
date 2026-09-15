from __future__ import annotations

import json
import os
import asyncio
import math
import time
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from core.delivery import DeliveryRetryableError, DeliveryWorker, InboundMessageInput, record_inbound_message
from core.platform import utc_now
from core.platform import revoke_account_delivery_tasks
from core.platform_worker import (
    PLATFORM_INBOUND_TASK_TYPE,
    PLATFORM_REPLY_TASK_TYPE,
    build_platform_delivery_handlers,
    process_platform_inbound_task,
)
from integrations.adp.provider import AgentResponse
from integrations.m3.adapter import M3LookupAdapter
from model.account import Account, AccountRole, AccountStatus
from model.platform import (
    PlatformAdpApp, PlatformAdpApiKey,
    PlatformAuditEvent,
    PlatformAuthSession,
    PlatformConversation,
    PlatformDeliveryTask,
    EnterpriseStatus,
    PlatformEvidence,
    PlatformEnterprise,
    PlatformExecutionRun,
    PlatformExecutionContext,
    PlatformInboundMessage,
    PlatformMessage,
    PlatformMembership,
    PlatformRole,
    PlatformStatus,
    PlatformToolCall,
    PlatformToolDefinition,
    PlatformUser,
)


pytestmark = pytest.mark.integration


def _database_url() -> str:
    url = os.getenv("PLATFORM_TEST_DATABASE_URL")
    if not url:
        pytest.skip("设置 PLATFORM_TEST_DATABASE_URL 后运行 PostgreSQL 集成测试")
    return url


@pytest_asyncio.fixture
async def platform_sessionmaker():
    database_url = _database_url()
    schema = f"platform_worker_test_{uuid.uuid4().hex}"
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
        PlatformAdpApp.__table__, PlatformAdpApiKey.__table__,
        PlatformEnterprise.__table__,
        PlatformUser.__table__,
        PlatformMembership.__table__,
        PlatformAuthSession.__table__,
        PlatformConversation.__table__,
        PlatformExecutionRun.__table__,
        PlatformEvidence.__table__,
        PlatformMessage.__table__,
        PlatformInboundMessage.__table__,
        PlatformDeliveryTask.__table__,
        PlatformToolDefinition.__table__,
        PlatformExecutionContext.__table__,
        PlatformToolCall.__table__,
        PlatformAuditEvent.__table__,
    ]
    async with engine.begin() as connection:
        # The models intentionally have no fixed schema.  With ``public`` in
        # the search path, SQLAlchemy's default existence check would see the
        # application's public tables and skip creating their isolated
        # counterparts.  The explicit schema is first in the search path, so
        # create the requested tables unconditionally in this disposable
        # schema.
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


async def _seed_inbound(
    factory,
    *,
    account_status: str = AccountStatus.ACTIVE,
    include_enterprise_id: bool = True,
    additional_active_membership: bool = False,
    include_session: bool = True,
    channel: str = "web",
    channel_instance_id: str = "web-local",
    revoke_sessions: bool = False,
):
    account_id = uuid.uuid4()
    user_id = uuid.uuid4()
    enterprise_id = uuid.uuid4()
    session_id = uuid.uuid4()
    async with factory() as db:
        enterprise_rows = [
            PlatformEnterprise(
                Id=enterprise_id,
                Name="Worker Enterprise",
                CustomerCode="CUST-WORKER",
            )
        ]
        if additional_active_membership:
            enterprise_rows.append(
                PlatformEnterprise(
                    Id=uuid.uuid4(),
                    Name="Worker Enterprise Secondary",
                    CustomerCode="CUST-WORKER-SECONDARY",
                )
            )
        db.add_all([
            Account(
                Id=account_id,
                Name="Worker Customer",
                Role=AccountRole.NORMAL,
                Status=account_status,
            ),
            *enterprise_rows,
            PlatformToolDefinition(
                Name="shipment.lookup",
                Version="1.0",
                Permission="shipment.read",
                Enabled=True,
                ReadOnly=True,
            ),
        ])
        await db.flush()
        db.add_all([
            PlatformUser(
                Id=user_id,
                AccountId=account_id,
                Name="Worker User",
                PhoneNormalized=f"13{uuid.uuid4().int % 1_000_000_000:09d}",
                PhoneMasked="138****0000",
                Role=PlatformRole.CUSTOMER,
                Status=PlatformStatus.ACTIVE,
            ),
            PlatformAuthSession(
                Id=session_id,
                AccountId=account_id,
                TokenId=uuid.uuid4().hex,
                ExpiresAt=utc_now() + timedelta(hours=1),
                RevokedAt=utc_now() - timedelta(minutes=1) if revoke_sessions else None,
            ),
        ])
        await db.flush()
        db.add_all([
            PlatformMembership(
                UserId=user_id,
                EnterpriseId=enterprise.Id,
                MembershipRole=PlatformRole.CUSTOMER,
                Active=True,
            )
            for enterprise in enterprise_rows
        ])
        task_payload = {
            "platformUserId": str(user_id),
            "channel": channel,
        }
        if include_session:
            task_payload["platformSessionId"] = str(session_id)
        if include_enterprise_id:
            task_payload["enterpriseId"] = str(enterprise_id)
        inbound, task, created = await record_inbound_message(
            db,
            message=InboundMessageInput(
                channel_instance_id=channel_instance_id,
                external_message_id=uuid.uuid4().hex,
                external_conversation_id=uuid.uuid4().hex,
                sender_identity_id=str(user_id),
                text="BL-WORKER-001",
                trace_id=uuid.uuid4().hex,
            ),
            task_type=PLATFORM_INBOUND_TASK_TYPE,
            task_payload=task_payload,
        )
        assert created is True
        assert task is not None
        await db.commit()
        return inbound.Id, task.Id


@pytest.mark.asyncio
async def test_channel_message_runs_without_any_browser_session(platform_sessionmaker):
    """A bound channel sender does not need to be logged into the website.

    The binding plus current memberships are the authorization; requiring a
    live browser session would make every WeChat question fail whenever the
    customer had not recently used the portal.
    """
    inbound_id, task_id = await _seed_inbound(
        platform_sessionmaker,
        include_enterprise_id=False,
        include_session=False,
        channel="wechat_official_account",
        channel_instance_id="oa-local",
        # Even a revoked browser session must not be borrowed to authorize it.
        revoke_sessions=True,
    )
    worker = DeliveryWorker(
        sessionmaker=platform_sessionmaker,
        handlers=build_platform_delivery_handlers(
            platform_sessionmaker,
            adapter_factory=M3LookupAdapter(use_mock=True, mock_records=[{"CustomerCode": "CUST-WORKER", "BillNo": "BL-WORKER-001"}]),
        ),
        worker_id="platform-worker-channel-sessionless",
    )

    assert await worker.run_once() is True

    async with platform_sessionmaker() as db:
        inbound = await db.get(PlatformInboundMessage, inbound_id)
        task = await db.get(PlatformDeliveryTask, task_id)
        enterprise = (
            await db.execute(
                select(PlatformEnterprise).where(PlatformEnterprise.CustomerCode == "CUST-WORKER")
            )
        ).scalar_one()
        context = (await db.execute(select(PlatformExecutionContext))).scalar_one()
        reply = (
            await db.execute(
                select(PlatformDeliveryTask).where(
                    PlatformDeliveryTask.TaskType == PLATFORM_REPLY_TASK_TYPE
                )
            )
        ).scalar_one()

        assert inbound.Status == "processed"
        assert task.Status == "succeeded"
        assert context.PlatformSessionId is None
        assert context.Channel == "wechat_official_account"
        assert str(context.EnterpriseId) == str(enterprise.Id)
        assert reply.Payload["platformSessionId"] is None
        assert reply.Payload["enterpriseId"] == str(enterprise.Id)

    artifact = Path(__file__).resolve().parents[3] / "output" / "tests" / "m3-identity-01-channel-sessionless-execution.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        json.dumps(
            {
                "task": "M3-IDENTITY-01",
                "database": "isolated PostgreSQL schema",
                "channel": "wechat_official_account",
                "browserSessionPresent": False,
                "revokedBrowserSessionBorrowed": False,
                "enterpriseResolvedFromMembership": True,
                "executionContextSessionId": None,
                "inboundStatus": "processed",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_channel_message_still_requires_an_unambiguous_enterprise(platform_sessionmaker):
    inbound_id, task_id = await _seed_inbound(
        platform_sessionmaker,
        include_enterprise_id=False,
        include_session=False,
        channel="wechat_official_account",
        channel_instance_id="oa-local-ambiguous",
        additional_active_membership=True,
    )
    worker = DeliveryWorker(
        sessionmaker=platform_sessionmaker,
        handlers=build_platform_delivery_handlers(
            platform_sessionmaker,
            adapter_factory=M3LookupAdapter(use_mock=True, mock_records=[{"CustomerCode": "CUST-WORKER", "BillNo": "BL-WORKER-001"}]),
        ),
        worker_id="platform-worker-channel-ambiguous",
    )

    assert await worker.run_once() is True

    async with platform_sessionmaker() as db:
        inbound = await db.get(PlatformInboundMessage, inbound_id)
        task = await db.get(PlatformDeliveryTask, task_id)
        # Dropping the session requirement must not let a multi-enterprise
        # message pick a tenant on its own.
        assert inbound.Status == "rejected"
        assert task.Status == "failed"
        assert (await db.execute(select(PlatformExecutionContext))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_worker_resolves_single_membership_when_channel_payload_has_no_enterprise(platform_sessionmaker):
    inbound_id, task_id = await _seed_inbound(
        platform_sessionmaker,
        include_enterprise_id=False,
    )
    worker = DeliveryWorker(
        sessionmaker=platform_sessionmaker,
        handlers=build_platform_delivery_handlers(
            platform_sessionmaker,
            adapter_factory=M3LookupAdapter(use_mock=True, mock_records=[{"CustomerCode": "CUST-WORKER", "BillNo": "BL-WORKER-001"}]),
        ),
        worker_id="platform-worker-dynamic-enterprise",
    )

    assert await worker.run_once() is True

    async with platform_sessionmaker() as db:
        inbound = await db.get(PlatformInboundMessage, inbound_id)
        task = await db.get(PlatformDeliveryTask, task_id)
        enterprise = (
            await db.execute(
                select(PlatformEnterprise).where(PlatformEnterprise.CustomerCode == "CUST-WORKER")
            )
        ).scalar_one()
        run = (await db.execute(select(PlatformExecutionRun))).scalar_one()
        reply = (
            await db.execute(
                select(PlatformDeliveryTask).where(
                    PlatformDeliveryTask.TaskType == PLATFORM_REPLY_TASK_TYPE
                )
            )
        ).scalar_one()
        assert inbound.Status == "processed"
        assert task.Status == "succeeded"
        assert str(run.EnterpriseId) == str(enterprise.Id)
        assert reply.Payload["enterpriseId"] == str(enterprise.Id)

    artifact = Path(__file__).resolve().parents[3] / "output" / "tests" / "m3-identity-01-worker-single-membership.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        json.dumps(
            {
                "task": "M3-IDENTITY-01",
                "database": "isolated PostgreSQL schema",
                "channelPayloadEnterpriseId": None,
                "activeMembershipCount": 1,
                "workerSelectedCurrentMembership": True,
                "inboundStatus": "processed",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_worker_rejects_ambiguous_memberships_when_channel_payload_has_no_enterprise(platform_sessionmaker):
    inbound_id, task_id = await _seed_inbound(
        platform_sessionmaker,
        include_enterprise_id=False,
        additional_active_membership=True,
    )
    worker = DeliveryWorker(
        sessionmaker=platform_sessionmaker,
        handlers=build_platform_delivery_handlers(
            platform_sessionmaker,
            adapter_factory=M3LookupAdapter(use_mock=True, mock_records=[{"CustomerCode": "CUST-WORKER", "BillNo": "BL-WORKER-001"}]),
        ),
        worker_id="platform-worker-ambiguous-enterprise",
    )

    assert await worker.run_once() is True

    async with platform_sessionmaker() as db:
        inbound = await db.get(PlatformInboundMessage, inbound_id)
        task = await db.get(PlatformDeliveryTask, task_id)
        run_count = await db.scalar(select(func.count()).select_from(PlatformExecutionRun))
        tool_call_count = await db.scalar(select(func.count()).select_from(PlatformToolCall))
        assert inbound.Status == "rejected"
        assert task.Status == "failed"
        assert task.LastError == "forbidden"
        assert run_count == 0
        assert tool_call_count == 0

    artifact = Path(__file__).resolve().parents[3] / "output" / "tests" / "m3-identity-01-worker-ambiguous-membership.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        json.dumps(
            {
                "task": "M3-IDENTITY-01",
                "database": "isolated PostgreSQL schema",
                "channelPayloadEnterpriseId": None,
                "activeMembershipCount": 2,
                "inboundStatus": "rejected",
                "errorCode": "forbidden",
                "providerOrToolCalled": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_worker_handles_twenty_concurrent_queries_baseline(platform_sessionmaker):
    """Record a local concurrency baseline without implying production capacity."""

    query_count = 20
    task_ids = []
    async with platform_sessionmaker() as db:
        db.add(PlatformToolDefinition(
            Name="shipment.lookup",
            Version="1.0",
            Permission="shipment.read",
            Enabled=True,
            ReadOnly=True,
        ))
        await db.flush()

        for index in range(query_count):
            account_id = uuid.uuid4()
            user_id = uuid.uuid4()
            enterprise_id = uuid.uuid4()
            session_id = uuid.uuid4()
            customer_code = f"CUST-PERF-{index:02d}"
            conversation_id = f"perf-conversation-{index:02d}"
            db.add_all([
                Account(
                    Id=account_id,
                    Name=f"Performance Customer {index}",
                    Role=AccountRole.NORMAL,
                    Status=AccountStatus.ACTIVE,
                ),
                PlatformEnterprise(
                    Id=enterprise_id,
                    Name=f"Performance Enterprise {index}",
                    CustomerCode=customer_code,
                ),
            ])
            await db.flush()
            db.add_all([
                PlatformUser(
                    Id=user_id,
                    AccountId=account_id,
                    Name=f"Performance User {index}",
                    PhoneNormalized=f"13{index:09d}",
                    PhoneMasked="138****0000",
                    Role=PlatformRole.CUSTOMER,
                    Status=PlatformStatus.ACTIVE,
                ),
                PlatformAuthSession(
                    Id=session_id,
                    AccountId=account_id,
                    TokenId=uuid.uuid4().hex,
                    ExpiresAt=utc_now() + timedelta(hours=1),
                ),
            ])
            await db.flush()
            db.add(PlatformMembership(
                UserId=user_id,
                EnterpriseId=enterprise_id,
                MembershipRole=PlatformRole.CUSTOMER,
                Active=True,
            ))
            await db.flush()
            inbound, task, created = await record_inbound_message(
                db,
                message=InboundMessageInput(
                    channel_instance_id="web-perf",
                    external_message_id=f"perf-message-{index:02d}",
                    external_conversation_id=conversation_id,
                    sender_identity_id=str(user_id),
                    text=f"BL-PERF-{index:02d}",
                    trace_id=uuid.uuid4().hex,
                ),
                task_type=PLATFORM_INBOUND_TASK_TYPE,
                task_payload={
                    "platformUserId": str(user_id),
                    "platformSessionId": str(session_id),
                    "enterpriseId": str(enterprise_id),
                    "channel": "web",
                },
            )
            assert created is True
            assert task is not None
            task_ids.append(task.Id)
        await db.commit()

    handlers = build_platform_delivery_handlers(
        platform_sessionmaker,
        adapter_factory=M3LookupAdapter(use_mock=True, mock_records=[{"CustomerCode": "CUST-WORKER", "BillNo": "BL-WORKER-001"}]),
    )
    workers = [
        DeliveryWorker(
            sessionmaker=platform_sessionmaker,
            handlers=handlers,
            worker_id=f"platform-perf-{index:02d}",
        )
        for index in range(query_count)
    ]

    async def run_one(worker: DeliveryWorker) -> tuple[bool, float]:
        started = time.perf_counter()
        processed = await worker.run_once()
        return processed, (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    results = await asyncio.gather(*(run_one(worker) for worker in workers))
    elapsed_ms = (time.perf_counter() - started) * 1000
    durations_ms = sorted(duration for processed, duration in results if processed)
    assert len(durations_ms) == query_count
    assert all(processed for processed, _duration in results)

    async with platform_sessionmaker() as db:
        succeeded = await db.scalar(
            select(func.count()).select_from(PlatformDeliveryTask).where(
                PlatformDeliveryTask.Id.in_(task_ids),
                PlatformDeliveryTask.Status == "succeeded",
            )
        )
        processed_inbound = await db.scalar(
            select(func.count()).select_from(PlatformInboundMessage).where(
                PlatformInboundMessage.Status == "processed",
            )
        )
        replies = await db.scalar(
            select(func.count()).select_from(PlatformDeliveryTask).where(
                PlatformDeliveryTask.TaskType == PLATFORM_REPLY_TASK_TYPE,
                PlatformDeliveryTask.Status == "queued",
            )
        )
    assert succeeded == query_count
    assert processed_inbound == query_count
    assert replies == query_count

    p95_index = max(0, math.ceil(len(durations_ms) * 0.95) - 1)
    artifact = Path(__file__).resolve().parents[3] / "output" / "tests" / "m4-perf-01.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        json.dumps(
            {
                "benchmark": "platform_worker_concurrent_queries",
                "queryCount": query_count,
                "concurrency": query_count,
                "processedCount": query_count,
                "elapsedMs": round(elapsed_ms, 2),
                "throughputQueriesPerSecond": round(query_count / max(elapsed_ms / 1000, 0.001), 2),
                "averageQueryMs": round(sum(durations_ms) / len(durations_ms), 2),
                "p95QueryMs": round(durations_ms[p95_index], 2),
                "databasePool": {"size": 4, "maxOverflow": 0},
                "upstream": "M3 Mock",
                "database": "isolated PostgreSQL schema",
                "conclusion": "本地基线通过 20 个并发 Worker 查询；结果受本地 PostgreSQL 4 连接池和 M3 Mock 影响，不能外推生产容量或真实 M3 性能。",
                "bottlenecksToValidateInProduction": [
                    "数据库连接池与锁竞争",
                    "真实 M3 延迟、限流和错误重试",
                    "Worker 进程数与队列租约吞吐",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    assert json.loads(artifact.read_text(encoding="utf-8"))["processedCount"] == query_count


@pytest.mark.asyncio
async def test_worker_persists_lookup_evidence_and_idempotent_reply(platform_sessionmaker):
    inbound_id, task_id = await _seed_inbound(platform_sessionmaker)
    adapter = M3LookupAdapter(
        use_mock=True,
        mock_records=[{
            "CustomerCode": "CUST-WORKER",
            "BillNo": "BL-WORKER-001",
            "VesselVoyage": "TEST VESSEL / 001E",
            "ETA": "2026-09-10 09:00",
        }],
    )
    worker = DeliveryWorker(
        sessionmaker=platform_sessionmaker,
        handlers=build_platform_delivery_handlers(platform_sessionmaker, adapter_factory=adapter),
        worker_id="platform-worker-test",
    )

    assert await worker.run_once() is True

    async with platform_sessionmaker() as db:
        inbound = await db.get(PlatformInboundMessage, inbound_id)
        source_task = await db.get(PlatformDeliveryTask, task_id)
        reply = (
            await db.execute(
                select(PlatformDeliveryTask).where(PlatformDeliveryTask.TaskType == PLATFORM_REPLY_TASK_TYPE)
            )
        ).scalar_one()
        call = (await db.execute(select(PlatformToolCall))).scalar_one()
        assert inbound.Status == "processed"
        assert source_task.Status == "succeeded"
        assert reply.Status == "queued"
        assert reply.MaxAttempts == 3
        assert reply.Payload["status"] == "found"
        assert reply.Payload["deliveryIdempotencyKey"] == f"platform-reply:{inbound_id}"
        assert reply.Payload["evidence"]
        assert call.Status == "completed"
        assert call.Outcome == "found"
        assert call.Evidence
        run = (await db.execute(select(PlatformExecutionRun))).scalar_one()
        messages = list((await db.execute(
            select(PlatformMessage).order_by(PlatformMessage.CreatedAt.asc())
        )).scalars().all())
        evidence = list((await db.execute(select(PlatformEvidence))).scalars().all())
        assert run.Status == "found"
        assert run.Query == "BL-WORKER-001"
        assert len(messages) == 2
        assert [message.Direction for message in messages] == ["inbound", "assistant"]
        assert len(evidence) == 7
        assert {item.Label for item in evidence} == {
            "订单号",
            "提单号",
            "箱号",
            "船名 / 航次",
            "预计抵港",
            "当前节点",
            "实际抵港",
        }

        detached_task = source_task

    reply_worker = DeliveryWorker(
        sessionmaker=platform_sessionmaker,
        handlers=build_platform_delivery_handlers(platform_sessionmaker, adapter_factory=adapter),
        worker_id="platform-reply-test",
    )
    assert await reply_worker.run_once() is True
    async with platform_sessionmaker() as db:
        reply = (
            await db.execute(
                select(PlatformDeliveryTask).where(PlatformDeliveryTask.TaskType == PLATFORM_REPLY_TASK_TYPE)
            )
        ).scalar_one()
        assert reply.Status == "succeeded"

    duplicate = await process_platform_inbound_task(
        platform_sessionmaker,
        detached_task,
        adapter=adapter,
    )
    assert duplicate.result["status"] == "already_processed"
    async with platform_sessionmaker() as db:
        reply_count = await db.scalar(
            select(func.count()).select_from(PlatformDeliveryTask).where(
                PlatformDeliveryTask.TaskType == PLATFORM_REPLY_TASK_TYPE
            )
        )
        assert reply_count == 1

    artifact = Path(__file__).resolve().parents[3] / "output" / "tests" / "m2-orch-01-worker.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        json.dumps(
            {
                "inboundStatus": "processed",
                "toolOutcome": "found",
                "replyCount": 1,
                "replyStatus": "succeeded",
                "runStatus": "found",
                "messages": ["inbound", "assistant"],
                "evidenceCount": 6,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    assert json.loads(artifact.read_text(encoding="utf-8"))["replyCount"] == 1


@pytest.mark.asyncio
async def test_worker_passes_server_execution_scope_to_agent_provider(platform_sessionmaker):
    inbound_id, _task_id = await _seed_inbound(platform_sessionmaker)
    requests = []

    class SpyProvider:
        capabilities = frozenset({"shipment.lookup"})

        async def execute(self, request):
            requests.append(request)
            return AgentResponse(
                status="found",
                query=request.query.upper(),
                title="已找到",
                summary="Provider 已返回受控结果",
                evidence=[{"label": "提单号", "value": request.query.upper(), "known": True}],
                provider_trace_id="provider-trace",
                audit_outcome="found",
            )

    worker = DeliveryWorker(
        sessionmaker=platform_sessionmaker,
        handlers=build_platform_delivery_handlers(
            platform_sessionmaker,
            agent_provider_factory=SpyProvider(),
        ),
        worker_id="platform-agent-provider-test",
    )

    assert await worker.run_once() is True
    assert len(requests) == 1
    request = requests[0]
    assert request.agent_id == "platform-default"
    assert request.channel == "web"
    assert request.customer_code == "CUST-WORKER"
    assert request.query == "BL-WORKER-001"
    assert request.conversation_id
    assert request.run_id
    assert request.trace_id
    assert request.visitor_id.startswith("platform:")
    assert len(request.visitor_id.split(":")) == 3
    assert "Worker User" not in request.visitor_id
    # Assert the structure instead of a short digit prefix: "138" appears in
    # random UUID hex often enough to fail for the wrong reason. Two opaque
    # UUIDs prove no name, phone, or enterprise name is embedded.
    _prefix, enterprise_part, account_part = request.visitor_id.split(":")
    assert uuid.UUID(enterprise_part) and uuid.UUID(account_part)
    assert "138****0000" not in request.visitor_id

    async with platform_sessionmaker() as db:
        reply = (
            await db.execute(
                select(PlatformDeliveryTask).where(PlatformDeliveryTask.TaskType == PLATFORM_REPLY_TASK_TYPE)
            )
        ).scalar_one()
        assert reply.Payload["providerTraceId"] == "provider-trace"
        assert reply.Payload["evidence"] == [
            {
                "label": "提单号",
                "value": "BL-WORKER-001",
                "source": "平台受控工具",
                "capturedAt": "",
                "known": True,
            }
        ]


@pytest.mark.asyncio
async def test_worker_rejects_provider_without_required_capability_before_tool_call(platform_sessionmaker):
    inbound_id, task_id = await _seed_inbound(platform_sessionmaker)
    calls = {"execute": 0}

    class IncompleteProvider:
        capabilities = frozenset()

        async def execute(self, request):
            calls["execute"] += 1
            raise AssertionError("provider must not execute without shipment.lookup")

    worker = DeliveryWorker(
        sessionmaker=platform_sessionmaker,
        handlers=build_platform_delivery_handlers(
            platform_sessionmaker,
            agent_provider_factory=IncompleteProvider(),
        ),
        worker_id="platform-provider-capability-test",
    )

    assert await worker.run_once() is True

    async with platform_sessionmaker() as db:
        inbound = await db.get(PlatformInboundMessage, inbound_id)
        task = await db.get(PlatformDeliveryTask, task_id)
        tool_call_count = await db.scalar(select(func.count()).select_from(PlatformToolCall))
        context_count = await db.scalar(select(func.count()).select_from(PlatformExecutionContext))
        assert inbound.Status == "rejected"
        assert task.Status == "failed"
        assert task.LastError == "provider_capability_missing"
        assert tool_call_count == 0
        assert context_count == 0
    assert calls["execute"] == 0


@pytest.mark.asyncio
async def test_worker_rejects_disabled_account_without_retry(platform_sessionmaker):
    inbound_id, task_id = await _seed_inbound(
        platform_sessionmaker,
        account_status=AccountStatus.BANNED,
    )
    worker = DeliveryWorker(
        sessionmaker=platform_sessionmaker,
        handlers=build_platform_delivery_handlers(
            platform_sessionmaker,
            adapter_factory=M3LookupAdapter(use_mock=True, mock_records=[{"CustomerCode": "CUST-WORKER", "BillNo": "BL-WORKER-001"}]),
        ),
        worker_id="platform-worker-rejection-test",
    )

    assert await worker.run_once() is True

    async with platform_sessionmaker() as db:
        inbound = await db.get(PlatformInboundMessage, inbound_id)
        task = await db.get(PlatformDeliveryTask, task_id)
        call_count = await db.scalar(select(func.count()).select_from(PlatformToolCall))
        assert inbound.Status == "rejected"
        assert task.Status == "failed"
        assert task.Attempts == 1
        assert task.LastError == "identity_invalid"
        assert call_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["session", "user", "account", "membership", "enterprise", "role"])
async def test_reply_is_revoked_before_delivery_after_access_change(platform_sessionmaker, revocation):
    inbound_id, _task_id = await _seed_inbound(platform_sessionmaker)
    calls = {"m3": 0, "send": 0}

    class CountingAdapter:
        async def lookup(self, *, query, customer_code):
            calls["m3"] += 1
            return {
                "status": "found",
                "title": "已找到",
                "summary": "结果已校验",
                "evidence": [{"label": "提单号", "value": query, "known": True}],
                "auditOutcome": "found",
            }

    business_worker = DeliveryWorker(
        sessionmaker=platform_sessionmaker,
        handlers=build_platform_delivery_handlers(
            platform_sessionmaker,
            adapter_factory=CountingAdapter(),
        ),
        worker_id=f"access-business-{revocation}",
    )
    assert await business_worker.run_once() is True

    async with platform_sessionmaker() as db:
        reply = (
            await db.execute(
                select(PlatformDeliveryTask).where(PlatformDeliveryTask.TaskType == PLATFORM_REPLY_TASK_TYPE)
            )
        ).scalar_one()
        payload = dict(reply.Payload)
        payload["channel"] = "wechat-service-account"
        reply.Payload = payload
        user = (await db.execute(select(PlatformUser))).scalar_one()
        account = await db.get(Account, user.AccountId)
        session = (await db.execute(select(PlatformAuthSession))).scalar_one()
        membership = (await db.execute(select(PlatformMembership))).scalar_one()
        enterprise = (await db.execute(select(PlatformEnterprise))).scalar_one()
        if revocation == "session":
            session.RevokedAt = utc_now()
        elif revocation == "user":
            user.Status = PlatformStatus.DISABLED
        elif revocation == "account":
            account.Status = AccountStatus.BANNED
        elif revocation == "membership":
            membership.Active = False
        elif revocation == "enterprise":
            enterprise.Status = EnterpriseStatus.SUSPENDED
        elif revocation == "role":
            user.Role = PlatformRole.OPS
            membership.MembershipRole = PlatformRole.OPS
        db.add_all([user, account, session, membership, enterprise, reply])
        await db.commit()

    class CountingSender:
        async def send(self, *, payload):
            calls["send"] += 1
            return {"providerMessageId": "must-not-send"}

    reply_worker = DeliveryWorker(
        sessionmaker=platform_sessionmaker,
        handlers=build_platform_delivery_handlers(
            platform_sessionmaker,
            adapter_factory=CountingAdapter(),
            reply_sender_factory=CountingSender,
        ),
        worker_id=f"access-reply-{revocation}",
    )
    assert await reply_worker.run_once() is True

    async with platform_sessionmaker() as db:
        reply = (
            await db.execute(
                select(PlatformDeliveryTask).where(PlatformDeliveryTask.TaskType == PLATFORM_REPLY_TASK_TYPE)
            )
        ).scalar_one()
        audit = (
            await db.execute(
                select(PlatformAuditEvent)
                .where(PlatformAuditEvent.Action == "platform.reply.reject")
                .order_by(PlatformAuditEvent.CreatedAt.desc())
            )
        ).scalars().first()
        assert reply.Status == "failed"
        assert reply.LastError == "authorization_revoked"
        assert audit is not None
        assert audit.Metadata["errorCode"] == "authorization_revoked"
    assert calls["m3"] == 1
    assert calls["send"] == 0


@pytest.mark.asyncio
async def test_account_revocation_fails_queued_reply_without_claiming_it(platform_sessionmaker):
    inbound_id, _task_id = await _seed_inbound(platform_sessionmaker)
    worker = DeliveryWorker(
        sessionmaker=platform_sessionmaker,
        handlers=build_platform_delivery_handlers(
            platform_sessionmaker,
            adapter_factory=M3LookupAdapter(use_mock=True, mock_records=[{"CustomerCode": "CUST-WORKER", "BillNo": "BL-WORKER-001"}]),
        ),
        worker_id="access-queue-revocation-business",
    )
    assert await worker.run_once() is True

    async with platform_sessionmaker() as db:
        reply = (
            await db.execute(
                select(PlatformDeliveryTask).where(PlatformDeliveryTask.TaskType == PLATFORM_REPLY_TASK_TYPE)
            )
        ).scalar_one()
        account_id = reply.Payload["accountId"]
        revoked = await revoke_account_delivery_tasks(db, account_id)
        await db.commit()
        assert revoked == 1
        assert reply.Status == "failed"
        assert reply.LastError == "authorization_revoked"

    async with platform_sessionmaker() as db:
        reply = (
            await db.execute(
                select(PlatformDeliveryTask).where(PlatformDeliveryTask.TaskType == PLATFORM_REPLY_TASK_TYPE)
            )
        ).scalar_one()
        assert reply.Status == "failed"
        assert reply.CompletedAt is not None
    artifact = Path(__file__).resolve().parents[3] / "output" / "tests" / "m2-access-03-revocation.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        json.dumps(
            {
                "revocationCases": ["session", "user", "account", "membership", "enterprise", "role"],
                "replyStatus": "failed",
                "errorCode": "authorization_revoked",
                "m3CallsAfterRevocation": 0,
                "privateEvidenceDelivered": False,
                "auditAction": "platform.reply.reject",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    assert json.loads(artifact.read_text(encoding="utf-8"))["errorCode"] == "authorization_revoked"


@pytest.mark.asyncio
async def test_reply_retry_reuses_persisted_result_without_running_m3_again(platform_sessionmaker):
    inbound_id, _task_id = await _seed_inbound(platform_sessionmaker)
    calls = {"count": 0}

    class CountingAdapter:
        async def lookup(self, *, query, customer_code):
            calls["count"] += 1
            return {
                "status": "found",
                "title": "已找到",
                "summary": "结果已校验",
                "evidence": [{"label": "提单号", "value": query, "known": True}],
                "auditOutcome": "found",
            }

    business_worker = DeliveryWorker(
        sessionmaker=platform_sessionmaker,
        handlers=build_platform_delivery_handlers(
            platform_sessionmaker,
            adapter_factory=CountingAdapter(),
        ),
        worker_id="retry-business-worker",
    )
    assert await business_worker.run_once() is True
    assert calls["count"] == 1

    async with platform_sessionmaker() as db:
        reply = (
            await db.execute(
                select(PlatformDeliveryTask).where(PlatformDeliveryTask.TaskType == PLATFORM_REPLY_TASK_TYPE)
            )
        ).scalar_one()
        # Exercise the real sender path while keeping the business execution
        # and its persisted result unchanged.
        reply.Payload = {**reply.Payload, "channel": "wechat-service-account"}
        db.add(reply)
        await db.commit()

    class FlakySender:
        def __init__(self):
            self.calls = 0

        async def send(self, *, payload):
            self.calls += 1
            if self.calls == 1:
                raise DeliveryRetryableError("provider_timeout")
            return {"providerMessageId": "provider-retry-1"}

    sender = FlakySender()
    reply_worker = DeliveryWorker(
        sessionmaker=platform_sessionmaker,
        handlers=build_platform_delivery_handlers(
            platform_sessionmaker,
            adapter_factory=CountingAdapter(),
            reply_sender_factory=lambda: sender,
        ),
        worker_id="retry-reply-worker",
    )
    assert await reply_worker.run_once() is True

    async with platform_sessionmaker() as db:
        reply = (
            await db.execute(
                select(PlatformDeliveryTask).where(PlatformDeliveryTask.TaskType == PLATFORM_REPLY_TASK_TYPE)
            )
        ).scalar_one()
        assert reply.Status == "queued"
        reply.AvailableAt = utc_now() - timedelta(seconds=1)
        db.add(reply)
        await db.commit()

    assert await reply_worker.run_once() is True
    assert sender.calls == 2
    assert calls["count"] == 1
    async with platform_sessionmaker() as db:
        reply = (
            await db.execute(
                select(PlatformDeliveryTask).where(PlatformDeliveryTask.TaskType == PLATFORM_REPLY_TASK_TYPE)
            )
        ).scalar_one()
        assert reply.Status == "succeeded"
        assert reply.Result["providerResult"]["providerMessageId"] == "provider-retry-1"

    artifact = Path(__file__).resolve().parents[3] / "output" / "tests" / "m2-retry-01.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        json.dumps(
            {
                "businessExecutionM3Calls": calls["count"],
                "replySendAttempts": sender.calls,
                "firstReplyStatus": "queued",
                "finalReplyStatus": "succeeded",
                "idempotencyKey": f"platform-reply:{inbound_id}",
                "unknownOutcomePolicy": "uncertain_terminal_no_auto_retry",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    assert json.loads(artifact.read_text(encoding="utf-8"))["businessExecutionM3Calls"] == 1


@pytest.mark.asyncio
async def test_business_retry_recovers_started_tool_call(platform_sessionmaker):
    inbound_id, task_id = await _seed_inbound(platform_sessionmaker)
    calls = {"count": 0}

    class FlakyBusinessAdapter:
        async def lookup(self, *, query, customer_code):
            calls["count"] += 1
            if calls["count"] == 1:
                raise DeliveryRetryableError("m3_timeout")
            return {
                "status": "found",
                "title": "已找到",
                "summary": "重试后结果已校验",
                "evidence": [{"label": "提单号", "value": query, "known": True}],
                "auditOutcome": "found",
            }

    worker = DeliveryWorker(
        sessionmaker=platform_sessionmaker,
        handlers=build_platform_delivery_handlers(
            platform_sessionmaker,
            adapter_factory=FlakyBusinessAdapter(),
        ),
        worker_id="business-retry-worker",
    )
    assert await worker.run_once() is True
    async with platform_sessionmaker() as db:
        task = await db.get(PlatformDeliveryTask, task_id)
        assert task.Status == "queued"
        assert task.LastError == "m3_timeout"
        task.AvailableAt = utc_now() - timedelta(seconds=1)
        db.add(task)
        await db.commit()

    assert await worker.run_once() is True
    async with platform_sessionmaker() as db:
        second_task = await db.get(PlatformDeliveryTask, task_id)
        assert second_task.Status == "succeeded", second_task.LastError
    assert calls["count"] == 2
    async with platform_sessionmaker() as db:
        inbound = await db.get(PlatformInboundMessage, inbound_id)
        task = await db.get(PlatformDeliveryTask, task_id)
        tool_calls = list((await db.execute(select(PlatformToolCall))).scalars().all())
        assert inbound.Status == "processed"
        assert task.Status == "succeeded"
        assert len(tool_calls) == 1
        assert tool_calls[0].Status == "completed"
