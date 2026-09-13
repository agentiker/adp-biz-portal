from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import core.delivery as delivery
from core.delivery import (
    DeliveryTaskError,
    DeliveryUncertainError,
    DeliveryRetryableError,
    DeliveryWorker,
    InboundMessageInput,
    TASK_FAILED,
    TASK_QUEUED,
    TASK_RUNNING,
    TASK_SUCCEEDED,
    TASK_UNCERTAIN,
    claim_next_delivery_task,
    complete_delivery_task,
    enqueue_delivery_task,
    fail_delivery_task,
    record_inbound_message,
)
from core.platform import utc_now
from model.platform import PlatformDeliveryTask, PlatformInboundMessage


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return self.value if isinstance(self.value, list) else []


class NestedTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


def fake_session(*results):
    return SimpleNamespace(
        execute=AsyncMock(side_effect=[ScalarResult(value) for value in results]),
        add=Mock(),
        flush=AsyncMock(),
        begin_nested=Mock(return_value=NestedTransaction()),
        commit=AsyncMock(),
        close=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_enqueue_delivery_task_is_idempotent():
    session = fake_session(None)

    task, created = await enqueue_delivery_task(
        session,
        task_type="channel.reply",
        deduplication_key="wechat:message-1",
        conversation_key="wechat:conversation-1",
        payload={"text": "hello"},
    )

    assert created is True
    assert task.Status == TASK_QUEUED
    assert task.MaxAttempts == 5
    assert task.Payload == {"text": "hello"}
    session.flush.assert_awaited_once()

    existing = PlatformDeliveryTask(
        TaskType="channel.reply",
        DeduplicationKey="wechat:message-1",
        Status=TASK_SUCCEEDED,
    )
    duplicate_session = fake_session(existing)
    duplicate, duplicate_created = await enqueue_delivery_task(
        duplicate_session,
        task_type="channel.reply",
        deduplication_key="wechat:message-1",
    )

    assert duplicate is existing
    assert duplicate_created is False
    duplicate_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_record_inbound_message_deduplicates_provider_callbacks():
    existing = PlatformInboundMessage(
        ChannelInstanceId="wechat",
        ExternalMessageId="message-1",
        ExternalConversationId="conversation-1",
        SenderIdentityId="sender-1",
        TraceId="trace-1",
    )
    session = fake_session(existing)

    inbound, task, created = await record_inbound_message(
        session,
        message=InboundMessageInput(
            channel_instance_id="wechat",
            external_message_id="message-1",
            external_conversation_id="conversation-1",
            sender_identity_id="sender-1",
            text="重复回调",
            trace_id="trace-2",
        ),
        task_type="channel.process",
    )

    assert inbound is existing
    assert task is None
    assert created is False
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_claim_query_serializes_conversations_and_recovers_expired_lease():
    ready = PlatformDeliveryTask(
        TaskType="channel.reply",
        DeduplicationKey="m-2",
        ConversationKey="wechat:c-2",
        Status=TASK_RUNNING,
        Attempts=1,
        LeaseUntil=utc_now() - timedelta(seconds=1),
    )
    session = fake_session(ready)

    task = await claim_next_delivery_task(session, worker_id="worker-2", lease_seconds=30)

    assert task is ready
    assert ready.Status == TASK_RUNNING
    assert ready.Attempts == 2
    assert ready.LeaseOwner == "worker-2"
    assert ready.LeaseUntil > utc_now()
    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": False}))
    assert "EXISTS" in sql
    assert "platform_delivery_task_2.\"ConversationKey\" = platform_delivery_task_1.\"ConversationKey\"" in sql
    assert "FOR UPDATE" in sql


@pytest.mark.asyncio
async def test_task_failure_is_bounded_and_uncertain_result_is_terminal(tmp_path):
    task = PlatformDeliveryTask(
        Id="task-1",
        Status=TASK_RUNNING,
        LeaseOwner="worker-1",
        LeaseUntil=utc_now() + timedelta(seconds=30),
        Attempts=1,
        MaxAttempts=3,
    )
    session = fake_session()

    await fail_delivery_task(
        session,
        task=task,
        worker_id="worker-1",
        error_code="provider_timeout",
    )
    assert task.Status == TASK_QUEUED
    assert task.AvailableAt > utc_now()
    assert task.LeaseOwner is None

    task.Status = TASK_RUNNING
    task.LeaseOwner = "worker-1"
    task.LeaseUntil = utc_now() + timedelta(seconds=30)
    task.Attempts = task.MaxAttempts
    await fail_delivery_task(
        session,
        task=task,
        worker_id="worker-1",
        error_code="provider_error",
    )
    assert task.Status == TASK_FAILED
    assert task.CompletedAt is not None

    task.Status = TASK_RUNNING
    task.LeaseOwner = "worker-1"
    task.LeaseUntil = utc_now() + timedelta(seconds=30)
    await fail_delivery_task(
        session,
        task=task,
        worker_id="worker-1",
        error_code="send_result_uncertain",
        uncertain=True,
    )
    assert task.Status == TASK_UNCERTAIN

    artifact = tmp_path / "delivery-task-state.json"
    artifact.write_text(
        json.dumps(
            {"retryStatus": TASK_QUEUED, "maxAttemptStatus": TASK_FAILED, "uncertainStatus": TASK_UNCERTAIN},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert json.loads(artifact.read_text(encoding="utf-8"))["uncertainStatus"] == TASK_UNCERTAIN


@pytest.mark.asyncio
async def test_worker_commits_claim_before_external_handler(monkeypatch):
    task = PlatformDeliveryTask(Id="task-1", TaskType="channel.reply")
    session = fake_session()
    events: list[str] = []

    async def claim(*_args, **_kwargs):
        events.append("claim")
        return task

    async def handler(_task):
        events.append("handler")
        assert "commit" in events
        return {"delivered": True}

    original_commit = session.commit

    async def commit():
        events.append("commit")
        await original_commit()

    session.commit = commit
    monkeypatch.setattr(delivery, "claim_next_delivery_task", claim)
    worker = DeliveryWorker(
        sessionmaker=lambda: session,
        handlers={"channel.reply": handler},
        worker_id="worker-1",
    )
    monkeypatch.setattr(worker, "_finalize", AsyncMock())

    assert await worker.run_once() is True
    assert events == ["claim", "commit", "handler"]


@pytest.mark.asyncio
async def test_worker_marks_unknown_send_outcome_without_retry(monkeypatch):
    task = PlatformDeliveryTask(Id="task-2", TaskType="channel.reply")
    session = fake_session()

    async def claim(*_args, **_kwargs):
        return task

    async def handler(_task):
        raise DeliveryUncertainError()

    monkeypatch.setattr(delivery, "claim_next_delivery_task", claim)
    finalize = AsyncMock()
    worker = DeliveryWorker(
        sessionmaker=lambda: session,
        handlers={"channel.reply": handler},
        worker_id="worker-1",
    )
    monkeypatch.setattr(worker, "_finalize", finalize)

    assert await worker.run_once() is True
    finalize.assert_awaited_once_with(
        "task-2",
        error_code="delivery_result_uncertain",
        retryable=False,
        uncertain=True,
    )


@pytest.mark.asyncio
async def test_worker_retries_only_explicit_transient_failures(monkeypatch):
    task = PlatformDeliveryTask(Id="task-retry", TaskType="channel.reply")
    session = fake_session()

    async def claim(*_args, **_kwargs):
        return task

    async def handler(_task):
        raise DeliveryRetryableError("provider_timeout")

    monkeypatch.setattr(delivery, "claim_next_delivery_task", claim)
    finalize = AsyncMock()
    worker = DeliveryWorker(
        sessionmaker=lambda: session,
        handlers={"channel.reply": handler},
        worker_id="worker-1",
    )
    monkeypatch.setattr(worker, "_finalize", finalize)

    assert await worker.run_once() is True
    finalize.assert_awaited_once_with(
        "task-retry",
        error_code="provider_timeout",
        retryable=True,
    )


@pytest.mark.asyncio
async def test_worker_does_not_retry_unclassified_handler_failure(monkeypatch):
    task = PlatformDeliveryTask(Id="task-failed", TaskType="channel.reply")
    session = fake_session()

    async def claim(*_args, **_kwargs):
        return task

    async def handler(_task):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(delivery, "claim_next_delivery_task", claim)
    finalize = AsyncMock()
    worker = DeliveryWorker(
        sessionmaker=lambda: session,
        handlers={"channel.reply": handler},
        worker_id="worker-1",
    )
    monkeypatch.setattr(worker, "_finalize", finalize)

    assert await worker.run_once() is True
    finalize.assert_awaited_once_with(
        "task-failed",
        error_code="handler_error",
        retryable=False,
    )


def test_worker_validation_rejects_invalid_lease_owner():
    task = PlatformDeliveryTask(Status=TASK_SUCCEEDED, LeaseOwner="worker-1")
    with pytest.raises(DeliveryTaskError):
        delivery._assert_lease(task, "worker-1")
