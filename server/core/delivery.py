"""Durable inbound-message and outbound-delivery task primitives.

The API only keeps a short database transaction open while it records or
claims work.  A worker executes channel/ADP calls after the claim is
committed, then opens a new transaction to finalize the task.  This prevents
slow provider calls from holding database connections or locks.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable, Mapping

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from core.platform import utc_now
from model.platform import PlatformDeliveryTask, PlatformInboundMessage


TASK_QUEUED = "queued"
TASK_RUNNING = "running"
TASK_SUCCEEDED = "succeeded"
TASK_FAILED = "failed"
TASK_UNCERTAIN = "uncertain"
TASK_TERMINAL_STATUSES = frozenset({TASK_SUCCEEDED, TASK_FAILED, TASK_UNCERTAIN})


class DeliveryTaskError(RuntimeError):
    """Raised when a task cannot be claimed or finalized by its worker."""


class DeliveryUncertainError(RuntimeError):
    """The provider outcome is unknown and must not be retried automatically."""


class DeliveryRetryableError(RuntimeError):
    """A known transient failure that may be retried within task limits."""

    def __init__(self, error_code: str = "delivery_retryable"):
        self.error_code = error_code if isinstance(error_code, str) and error_code.strip() else "delivery_retryable"
        super().__init__(self.error_code)


class DeliveryRejectedError(RuntimeError):
    """The task is invalid or unauthorized and must not be retried."""

    def __init__(self, error_code: str = "task_rejected"):
        self.error_code = _text(error_code, field="错误码", limit=128) or "task_rejected"
        super().__init__(self.error_code)


@dataclass(frozen=True)
class InboundMessageInput:
    channel_instance_id: str
    external_message_id: str
    external_conversation_id: str
    sender_identity_id: str
    text: str | None
    trace_id: str
    message_type: str = "text"
    payload: Mapping[str, Any] | None = None
    # Latest moment the source channel still accepts a reply for this message.
    # Adapters derive it from their protocol window; the portal leaves it unset
    # because the browser reads the answer back instead of being pushed to.
    reply_window_expires_at: datetime | None = None


@dataclass(frozen=True)
class DeliveryOutcome:
    """Safe, structured data returned by a delivery handler."""

    result: Mapping[str, Any] | None = None


DeliveryHandler = Callable[[PlatformDeliveryTask], Awaitable[DeliveryOutcome | Mapping[str, Any] | None]]


def _text(value: Any, *, field: str, limit: int, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise DeliveryTaskError(f"{field}格式不正确")
    normalized = value.strip()
    if required and not normalized:
        raise DeliveryTaskError(f"{field}不能为空")
    if len(normalized) > limit:
        raise DeliveryTaskError(f"{field}长度超限")
    return normalized


def _payload(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise DeliveryTaskError("任务载荷格式不正确")
    return dict(value)


def _reply_deadline(value: Any) -> datetime | None:
    """Normalize a channel reply deadline to a naive UTC timestamp."""
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise DeliveryTaskError("回复截止时间格式不正确")
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _max_attempts(value: int) -> int:
    try:
        attempts = int(value)
    except (TypeError, ValueError) as exc:
        raise DeliveryTaskError("最大重试次数格式不正确") from exc
    if attempts < 1 or attempts > 20:
        raise DeliveryTaskError("最大重试次数必须在 1 到 20 之间")
    return attempts


async def _find_existing_task(db: AsyncSession, deduplication_key: str) -> PlatformDeliveryTask | None:
    return (
        await db.execute(
            select(PlatformDeliveryTask).where(
                PlatformDeliveryTask.DeduplicationKey == deduplication_key,
            )
        )
    ).scalar_one_or_none()


async def enqueue_delivery_task(
    db: AsyncSession,
    *,
    task_type: str,
    deduplication_key: str,
    payload: Mapping[str, Any] | None = None,
    conversation_key: str | None = None,
    max_attempts: int = 5,
    available_at: datetime | None = None,
) -> tuple[PlatformDeliveryTask, bool]:
    """Insert one durable task, returning ``(task, created)``.

    The unique key is checked inside a savepoint so a concurrent duplicate
    does not roll back a caller's surrounding inbound-message transaction.
    """

    task_name = _text(task_type, field="任务类型", limit=64)
    dedup = _text(deduplication_key, field="幂等键", limit=255)
    conversation = _text(conversation_key, field="会话键", limit=255, required=False)
    attempts = _max_attempts(max_attempts)
    if available_at is not None and not isinstance(available_at, datetime):
        raise DeliveryTaskError("任务可用时间格式不正确")

    existing = await _find_existing_task(db, dedup)
    if existing is not None:
        return existing, False

    task = PlatformDeliveryTask(
        TaskType=task_name,
        DeduplicationKey=dedup,
        ConversationKey=conversation,
        Payload=_payload(payload),
        Status=TASK_QUEUED,
        MaxAttempts=attempts,
        AvailableAt=available_at or utc_now(),
    )
    try:
        async with db.begin_nested():
            db.add(task)
            await db.flush()
    except IntegrityError:
        existing = await _find_existing_task(db, dedup)
        if existing is None:
            raise
        return existing, False
    return task, True


async def record_inbound_message(
    db: AsyncSession,
    *,
    message: InboundMessageInput,
    task_type: str,
    task_payload: Mapping[str, Any] | None = None,
    max_attempts: int = 5,
) -> tuple[PlatformInboundMessage, PlatformDeliveryTask | None, bool]:
    """Persist an inbound envelope and its task in one transaction.

    ``created`` is false for a repeated provider callback.  The caller can
    acknowledge both new and duplicate callbacks without invoking the handler
    twice.
    """

    channel = _text(message.channel_instance_id, field="渠道实例", limit=128)
    external_id = _text(message.external_message_id, field="外部消息 ID", limit=255)
    external_conversation = _text(message.external_conversation_id, field="外部会话 ID", limit=255)
    sender = _text(message.sender_identity_id, field="发送者身份", limit=255)
    message_type = _text(message.message_type, field="消息类型", limit=32)
    trace_id = _text(message.trace_id, field="Trace ID", limit=64)
    text = _text(message.text, field="消息文本", limit=10000, required=False)

    existing = (
        await db.execute(
            select(PlatformInboundMessage).where(
                PlatformInboundMessage.ChannelInstanceId == channel,
                PlatformInboundMessage.ExternalMessageId == external_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, None, False

    inbound = PlatformInboundMessage(
        ChannelInstanceId=channel,
        ExternalMessageId=external_id,
        ExternalConversationId=external_conversation,
        SenderIdentityId=sender,
        MessageType=message_type,
        Text=text,
        Payload=_payload(message.payload),
        TraceId=trace_id,
        Status="accepted",
        ReplyWindowExpiresAt=_reply_deadline(message.reply_window_expires_at),
    )
    try:
        async with db.begin_nested():
            db.add(inbound)
            await db.flush()
    except IntegrityError:
        existing = (
            await db.execute(
                select(PlatformInboundMessage).where(
                    PlatformInboundMessage.ChannelInstanceId == channel,
                    PlatformInboundMessage.ExternalMessageId == external_id,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            raise
        return existing, None, False

    normalized_task_payload = _payload(task_payload)
    normalized_task_payload.setdefault("inboundMessageId", str(inbound.Id) if inbound.Id else None)
    task, created = await enqueue_delivery_task(
        db,
        task_type=task_type,
        deduplication_key=f"{channel}:{external_id}",
        payload=normalized_task_payload,
        conversation_key=f"{channel}:{external_conversation}",
        max_attempts=max_attempts,
    )
    inbound.Status = "queued" if created else "accepted"
    db.add(inbound)
    await db.flush()
    return inbound, task, created


def _ready_filter(task_model, now: datetime):
    return and_(
        or_(
            task_model.Status == TASK_QUEUED,
            and_(
                task_model.Status == TASK_RUNNING,
                task_model.LeaseUntil <= now,
            ),
        ),
        task_model.AvailableAt <= now,
        or_(task_model.LeaseUntil.is_(None), task_model.LeaseUntil <= now),
    )


async def claim_next_delivery_task(
    db: AsyncSession,
    *,
    worker_id: str,
    lease_seconds: int = 60,
) -> PlatformDeliveryTask | None:
    """Claim the oldest ready task while serializing each conversation key."""

    owner = _text(worker_id, field="Worker ID", limit=128)
    try:
        lease = int(lease_seconds)
    except (TypeError, ValueError) as exc:
        raise DeliveryTaskError("租约时长格式不正确") from exc
    if lease < 5 or lease > 3600:
        raise DeliveryTaskError("租约时长必须在 5 到 3600 秒之间")

    now = utc_now()
    candidate = aliased(PlatformDeliveryTask)
    blocker = aliased(PlatformDeliveryTask)
    is_earlier = or_(
        blocker.CreatedAt < candidate.CreatedAt,
        and_(blocker.CreatedAt == candidate.CreatedAt, blocker.Id < candidate.Id),
    )
    same_conversation_blocker = exists().where(
        blocker.Id != candidate.Id,
        blocker.ConversationKey == candidate.ConversationKey,
        or_(
            and_(blocker.Status == TASK_RUNNING, blocker.LeaseUntil > now),
            and_(blocker.Status.in_((TASK_QUEUED, TASK_RUNNING)), is_earlier),
        ),
    )
    result = await db.execute(
        select(candidate)
        .where(
            _ready_filter(candidate, now),
            or_(candidate.ConversationKey.is_(None), ~same_conversation_blocker),
        )
        .order_by(candidate.CreatedAt, candidate.Id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    task = result.scalar_one_or_none()
    if task is None:
        return None
    task.Status = TASK_RUNNING
    task.Attempts = int(task.Attempts or 0) + 1
    task.LeaseOwner = owner
    task.LeaseUntil = now + timedelta(seconds=lease)
    task.LastError = None
    db.add(task)
    await db.flush()
    return task


def _assert_lease(task: PlatformDeliveryTask, worker_id: str) -> None:
    if task.Status != TASK_RUNNING or task.LeaseOwner != worker_id:
        raise DeliveryTaskError("任务租约不属于当前 Worker")
    if task.LeaseUntil is None or task.LeaseUntil <= utc_now():
        raise DeliveryTaskError("任务租约已过期")


async def renew_delivery_lease(
    db: AsyncSession,
    *,
    task: PlatformDeliveryTask,
    worker_id: str,
    lease_seconds: int = 60,
) -> None:
    _assert_lease(task, worker_id)
    if lease_seconds < 5 or lease_seconds > 3600:
        raise DeliveryTaskError("租约时长必须在 5 到 3600 秒之间")
    task.LeaseUntil = utc_now() + timedelta(seconds=int(lease_seconds))
    db.add(task)
    await db.flush()


async def complete_delivery_task(
    db: AsyncSession,
    *,
    task: PlatformDeliveryTask,
    worker_id: str,
    result: Mapping[str, Any] | None = None,
) -> None:
    _assert_lease(task, worker_id)
    task.Status = TASK_SUCCEEDED
    task.Result = _payload(result)
    task.CompletedAt = utc_now()
    task.LeaseOwner = None
    task.LeaseUntil = None
    db.add(task)
    await db.flush()


def _backoff_seconds(attempts: int) -> int:
    return min(300, 2 ** max(0, min(int(attempts), 8) - 1))


async def fail_delivery_task(
    db: AsyncSession,
    *,
    task: PlatformDeliveryTask,
    worker_id: str,
    error_code: str,
    retryable: bool = True,
    uncertain: bool = False,
) -> None:
    """Finalize a task with bounded retry or an explicit uncertain state."""

    _assert_lease(task, worker_id)
    safe_error = _text(error_code, field="错误码", limit=128)
    now = utc_now()
    task.LastError = safe_error
    task.LeaseOwner = None
    task.LeaseUntil = None
    if uncertain:
        task.Status = TASK_UNCERTAIN
        task.CompletedAt = now
    elif not retryable or int(task.Attempts or 0) >= int(task.MaxAttempts or 1):
        task.Status = TASK_FAILED
        task.CompletedAt = now
    else:
        task.Status = TASK_QUEUED
        task.AvailableAt = now + timedelta(seconds=_backoff_seconds(int(task.Attempts or 0)))
    db.add(task)
    await db.flush()


class DeliveryWorker:
    """Small database-backed worker usable by channel and ADP delivery jobs."""

    def __init__(
        self,
        *,
        sessionmaker: Callable[[], AsyncSession],
        handlers: Mapping[str, DeliveryHandler],
        worker_id: str | None = None,
        lease_seconds: int = 60,
        idle_seconds: float = 1.0,
    ):
        self.sessionmaker = sessionmaker
        self.handlers = dict(handlers)
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex}"
        self.lease_seconds = lease_seconds
        self.idle_seconds = max(0.05, float(idle_seconds))

    async def _finalize(
        self,
        task_id: Any,
        *,
        outcome: DeliveryOutcome | Mapping[str, Any] | None = None,
        error_code: str | None = None,
        retryable: bool = True,
        uncertain: bool = False,
    ) -> None:
        db = self.sessionmaker()
        try:
            task = await db.get(PlatformDeliveryTask, task_id)
            if task is None:
                return
            if error_code is None:
                result = outcome.result if isinstance(outcome, DeliveryOutcome) else outcome
                await complete_delivery_task(db, task=task, worker_id=self.worker_id, result=result)
            else:
                await fail_delivery_task(
                    db,
                    task=task,
                    worker_id=self.worker_id,
                    error_code=error_code,
                    retryable=retryable,
                    uncertain=uncertain,
                )
            await db.commit()
        finally:
            await db.close()

    async def run_once(self) -> bool:
        """Claim and process one task; returns false when the queue is empty."""

        db = self.sessionmaker()
        try:
            task = await claim_next_delivery_task(
                db,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
            )
            await db.commit()
        finally:
            await db.close()
        if task is None:
            return False

        handler = self.handlers.get(task.TaskType)
        if handler is None:
            await self._finalize(task.Id, error_code="handler_not_registered", retryable=False)
            return True
        try:
            outcome = await handler(task)
        except DeliveryUncertainError:
            await self._finalize(
                task.Id,
                error_code="delivery_result_uncertain",
                retryable=False,
                uncertain=True,
            )
        except DeliveryRetryableError as exc:
            await self._finalize(
                task.Id,
                error_code=exc.error_code,
                retryable=True,
            )
        except DeliveryRejectedError as exc:
            await self._finalize(
                task.Id,
                error_code=exc.error_code,
                retryable=False,
            )
        except Exception:
            # Provider exception details stay out of task rows and customer
            # responses; operators can correlate the task ID and trace log.
            # Unclassified failures are terminal. A handler must explicitly
            # raise DeliveryRetryableError when a retry is safe.
            await self._finalize(task.Id, error_code="handler_error", retryable=False)
        else:
            await self._finalize(task.Id, outcome=outcome)
        return True

    async def run_forever(self, stop_event: asyncio.Event | None = None) -> None:
        stop = stop_event or asyncio.Event()
        while not stop.is_set():
            processed = await self.run_once()
            if processed:
                continue
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.idle_seconds)
            except asyncio.TimeoutError:
                continue
