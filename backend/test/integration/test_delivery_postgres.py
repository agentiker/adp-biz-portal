from __future__ import annotations

import os
import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from core.delivery import (
    InboundMessageInput,
    TASK_QUEUED,
    claim_next_delivery_task,
    complete_delivery_task,
    record_inbound_message,
)
from core.platform import utc_now
from model.platform import PlatformDeliveryTask, PlatformInboundMessage


pytestmark = pytest.mark.integration


def _database_url() -> str:
    url = os.getenv("PLATFORM_TEST_DATABASE_URL")
    if not url:
        pytest.skip("设置 PLATFORM_TEST_DATABASE_URL 后运行 PostgreSQL 集成测试")
    return url


@pytest_asyncio.fixture
async def postgres_sessionmaker():
    """Create the delivery tables in an isolated, disposable PostgreSQL schema."""

    database_url = _database_url()
    schema = f"platform_test_{uuid.uuid4().hex}"
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
    async with engine.begin() as connection:
        # Avoid SQLAlchemy resolving an existing public table through the
        # search path and silently skipping the isolated test table.
        await connection.run_sync(
            lambda sync_connection: PlatformInboundMessage.__table__.create(
                sync_connection,
                checkfirst=False,
            )
        )
        await connection.run_sync(
            lambda sync_connection: PlatformDeliveryTask.__table__.create(
                sync_connection,
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


def _task(*, key: str, conversation: str, created_at):
    return PlatformDeliveryTask(
        Id=str(uuid.uuid4()),
        TaskType="channel.process",
        DeduplicationKey=key,
        ConversationKey=conversation,
        Payload={"key": key},
        Status=TASK_QUEUED,
        Attempts=0,
        MaxAttempts=3,
        AvailableAt=utc_now() - timedelta(seconds=1),
        CreatedAt=created_at,
    )


@pytest.mark.asyncio
async def test_postgres_records_inbound_message_once(postgres_sessionmaker):
    first_message = InboundMessageInput(
        channel_instance_id="wechat-service-account",
        external_message_id="external-1",
        external_conversation_id="conversation-1",
        sender_identity_id="sender-1",
        text="查询提单",
        trace_id="trace-1",
    )
    async with postgres_sessionmaker() as db:
        inbound, task, created = await record_inbound_message(
            db,
            message=first_message,
            task_type="channel.process",
        )
        await db.commit()

        duplicate, duplicate_task, duplicate_created = await record_inbound_message(
            db,
            message=first_message,
            task_type="channel.process",
        )
        assert duplicate.Id == inbound.Id
        assert duplicate_task is None
        assert duplicate_created is False
        assert task is not None
        assert created is True

        inbound_count = await db.scalar(select(func.count()).select_from(PlatformInboundMessage))
        task_count = await db.scalar(select(func.count()).select_from(PlatformDeliveryTask))
        assert inbound_count == 1
        assert task_count == 1


@pytest.mark.asyncio
async def test_postgres_claims_different_conversations_concurrently_but_preserves_fifo(postgres_sessionmaker):
    base_time = utc_now()
    async with postgres_sessionmaker() as db:
        db.add_all(
            [
                _task(key="c1-old", conversation="conversation-1", created_at=base_time),
                _task(
                    key="c1-new",
                    conversation="conversation-1",
                    created_at=base_time + timedelta(seconds=1),
                ),
                _task(
                    key="c2-first",
                    conversation="conversation-2",
                    created_at=base_time + timedelta(seconds=2),
                ),
            ]
        )
        await db.commit()

    first_db = postgres_sessionmaker()
    second_db = postgres_sessionmaker()
    try:
        first = await claim_next_delivery_task(first_db, worker_id="worker-1", lease_seconds=30)
        assert first is not None
        assert first.DeduplicationKey == "c1-old"
        await complete_delivery_task(first_db, task=first, worker_id="worker-1", result={"ok": True})

        second = await claim_next_delivery_task(second_db, worker_id="worker-2", lease_seconds=30)
        assert second is not None
        assert second.DeduplicationKey == "c2-first"
        await second_db.commit()

        await first_db.commit()
    finally:
        await first_db.close()
        await second_db.close()

    async with postgres_sessionmaker() as db:
        next_task = await claim_next_delivery_task(db, worker_id="worker-3", lease_seconds=30)
        assert next_task is not None
        assert next_task.DeduplicationKey == "c1-new"
        await db.commit()


@pytest.mark.asyncio
async def test_postgres_reclaims_expired_lease(postgres_sessionmaker):
    created_at = utc_now()
    async with postgres_sessionmaker() as db:
        db.add(_task(key="lease-1", conversation="conversation-lease", created_at=created_at))
        await db.commit()

    async with postgres_sessionmaker() as db:
        claimed = await claim_next_delivery_task(db, worker_id="worker-1", lease_seconds=30)
        assert claimed is not None
        assert claimed.Attempts == 1
        await db.commit()

    async with postgres_sessionmaker() as db:
        task = (
            await db.execute(
                select(PlatformDeliveryTask).where(PlatformDeliveryTask.DeduplicationKey == "lease-1")
            )
        ).scalar_one()
        task.LeaseUntil = utc_now() - timedelta(seconds=1)
        await db.commit()

    async with postgres_sessionmaker() as db:
        recovered = await claim_next_delivery_task(db, worker_id="worker-2", lease_seconds=30)
        assert recovered is not None
        assert recovered.DeduplicationKey == "lease-1"
        assert recovered.Attempts == 2
        await db.commit()
