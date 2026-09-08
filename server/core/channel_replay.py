"""Cross-instance replay protection for signed channel callbacks.

A signed provider callback must be accepted at most once for the whole
deployment, not once per API process. The unique constraint on
``platform_channel_replay_marker`` is what rejects a replay, so the guarantee
holds across instances and process restarts.

This is separate from message-level deduplication: an inbound message is
deduplicated by ``(ChannelInstanceId, ExternalMessageId)`` so a legitimate
provider retry still executes the business query only once. Replay protection
here rejects a *replayed signature*, which a legitimate retry never reuses.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.error.platform import PlatformBadRequest
from core.platform import utc_now
from model.platform import PlatformChannelReplayMarker


MAX_REPLAY_KEY_LENGTH = 64
PRUNE_BATCH = 500


class ChannelReplayError(PlatformBadRequest):
    """The callback signature was already accepted by this deployment."""


def _text(value: object, *, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ChannelReplayError(f"{field}格式不正确")
    return value.strip()


async def claim_replay_key(
    db: AsyncSession,
    *,
    channel: str,
    channel_instance_id: str,
    replay_key: str,
    ttl_seconds: int,
) -> None:
    """Record one accepted callback signature, rejecting a repeat.

    The caller must not have committed anything it needs to keep when this
    raises: a rejected replay is expected to abort the whole callback.
    """
    channel_name = _text(channel, field="渠道", limit=48)
    instance_id = _text(channel_instance_id, field="渠道实例", limit=128)
    key = _text(replay_key, field="回调重放标识", limit=MAX_REPLAY_KEY_LENGTH)
    try:
        ttl = int(ttl_seconds)
    except (TypeError, ValueError) as exc:
        raise ChannelReplayError("回调重放窗口格式不正确") from exc
    if ttl < 1 or ttl > 24 * 60 * 60:
        raise ChannelReplayError("回调重放窗口不受支持")

    now = utc_now()
    existing = (
        await db.execute(
            select(PlatformChannelReplayMarker).where(
                PlatformChannelReplayMarker.Channel == channel_name,
                PlatformChannelReplayMarker.ChannelInstanceId == instance_id,
                PlatformChannelReplayMarker.ReplayKey == key,
                PlatformChannelReplayMarker.ExpiresAt > now,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ChannelReplayError("渠道回调重复提交")

    marker = PlatformChannelReplayMarker(
        Channel=channel_name,
        ChannelInstanceId=instance_id,
        ReplayKey=key,
        ExpiresAt=now + timedelta(seconds=ttl),
    )
    try:
        async with db.begin_nested():
            db.add(marker)
            await db.flush()
    except IntegrityError as exc:
        # A concurrent instance won the race, or an expired row still holds the
        # key. Either way this exact signature has already been accepted.
        raise ChannelReplayError("渠道回调重复提交") from exc


async def prune_expired_replay_markers(db: AsyncSession, *, limit: int = PRUNE_BATCH) -> int:
    """Delete a bounded batch of expired markers.

    Pruning is opportunistic so a callback never waits on a large delete; the
    unique constraint keeps working whether or not pruning has caught up.
    """
    expired = list(
        (
            await db.execute(
                select(PlatformChannelReplayMarker.Id)
                .where(PlatformChannelReplayMarker.ExpiresAt <= utc_now())
                .limit(max(1, int(limit)))
            )
        ).scalars().all()
    )
    if not expired:
        return 0
    await db.execute(
        delete(PlatformChannelReplayMarker).where(PlatformChannelReplayMarker.Id.in_(expired))
    )
    return len(expired)
