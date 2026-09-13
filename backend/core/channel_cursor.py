"""Durable sync cursors for pull-based channels (WeChat 客服 sync_msg).

The cursor is persisted so the position survives API/worker restarts and is
shared across instances. Callers store ``next_cursor`` BEFORE dispatching a
page, so a crash never re-reads and re-dispatches an already-processed page;
duplicate delivery is caught separately by external-message-id idempotency.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.platform import utc_now
from model.platform import PlatformChannelCursor


MAX_CURSOR_LENGTH = 1024


def normalize_scope_id(scope_id: str | None) -> str:
    """A channel-instance sub-scope (e.g. WeChat 客服 open_kfid); "all" when none."""
    value = scope_id.strip() if isinstance(scope_id, str) else ""
    return value[:128] if value else "all"


async def get_cursor(
    db: AsyncSession, *, channel: str, channel_instance_id: str, scope_id: str | None
) -> str | None:
    row = (
        await db.execute(
            select(PlatformChannelCursor).where(
                PlatformChannelCursor.Channel == channel,
                PlatformChannelCursor.ChannelInstanceId == channel_instance_id,
                PlatformChannelCursor.ScopeId == normalize_scope_id(scope_id),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return row.Cursor or None


async def set_cursor(
    db: AsyncSession, *, channel: str, channel_instance_id: str, scope_id: str | None, cursor: str
) -> None:
    """Upsert the stored cursor for a scope (call BEFORE dispatching the page)."""
    scope = normalize_scope_id(scope_id)
    value = (cursor or "")[:MAX_CURSOR_LENGTH]
    row = (
        await db.execute(
            select(PlatformChannelCursor).where(
                PlatformChannelCursor.Channel == channel,
                PlatformChannelCursor.ChannelInstanceId == channel_instance_id,
                PlatformChannelCursor.ScopeId == scope,
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        row.Cursor = value
        row.UpdatedAt = utc_now()
        db.add(row)
        return
    db.add(
        PlatformChannelCursor(
            Channel=channel,
            ChannelInstanceId=channel_instance_id,
            ScopeId=scope,
            Cursor=value,
            UpdatedAt=utc_now(),
        )
    )
    try:
        await db.flush()
    except IntegrityError:
        # A concurrent writer created the row first; fall back to updating it.
        await db.rollback()
        existing = (
            await db.execute(
                select(PlatformChannelCursor).where(
                    PlatformChannelCursor.Channel == channel,
                    PlatformChannelCursor.ChannelInstanceId == channel_instance_id,
                    PlatformChannelCursor.ScopeId == scope,
                )
            )
        ).scalar_one()
        existing.Cursor = value
        existing.UpdatedAt = utc_now()
        db.add(existing)
