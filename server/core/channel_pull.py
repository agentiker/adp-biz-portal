"""Cursor-paged inbound pull for WeChat 客服 (kf/sync_msg).

The 客服 callback is only a notification; messages are pulled here. Correctness
rules (the reference adapters that skip them lose messages):

- persist ``next_cursor`` and enqueue a page's messages in one committed
  transaction, per page, so a crash resumes at the next page and never
  re-dispatches a committed one;
- loop while ``has_more``;
- send the callback ``token`` only on the first pull (no stored cursor);
- dispatch EVERY item in a page (not just the last), deduped by external
  message id via the shared ingress seam.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from core.channel_cursor import get_cursor, set_cursor
from core.channel_ingress import resolve_and_enqueue_inbound
from core.platform_worker import PLATFORM_INBOUND_MAX_ATTEMPTS, PLATFORM_INBOUND_TASK_TYPE


logger = logging.getLogger(__name__)

MAX_SYNC_PAGES = 100


class _KfSyncTransport(Protocol):
    async def sync_msg(self, *, cursor: str, open_kfid: str, callback_token: str | None) -> Mapping[str, Any]: ...


class _KfAdapter(Protocol):
    channel: str
    channel_instance_id: str

    def normalize_item(self, item: Mapping[str, Any], *, trace_id: str, now: float | None = None) -> Any: ...


async def sync_wechat_kf(
    db: AsyncSession,
    *,
    adapter: _KfAdapter,
    transport: _KfSyncTransport,
    open_kfid: str,
    callback_token: str,
    trace_id: str,
    now: float | None = None,
    max_pages: int = MAX_SYNC_PAGES,
    dispatch: bool = True,
) -> dict[str, int]:
    """Pull and enqueue new 客服 messages. Returns counts for observability.

    ``dispatch=False`` drains the backlog without enqueuing (first-boot prime),
    so a fresh install does not replay history.
    """
    cursor = (await get_cursor(
        db, channel=adapter.channel, channel_instance_id=adapter.channel_instance_id, scope_id=open_kfid
    )) or ""
    pages = 0
    seen = 0
    enqueued = 0
    while pages < max_pages:
        response = await transport.sync_msg(
            cursor=cursor, open_kfid=open_kfid, callback_token=(callback_token if not cursor else None)
        )
        next_cursor = str(response.get("next_cursor") or "")
        has_more = int(response.get("has_more") or 0) == 1
        # Persist the cursor with this page's enqueue, atomically, before moving on.
        await set_cursor(
            db, channel=adapter.channel, channel_instance_id=adapter.channel_instance_id,
            scope_id=open_kfid, cursor=next_cursor,
        )
        for item in response.get("msg_list") or []:
            seen += 1
            if not dispatch:
                continue
            envelope = adapter.normalize_item(item, trace_id=trace_id, now=now)
            if envelope is None:
                continue
            result = await resolve_and_enqueue_inbound(
                db,
                channel=adapter.channel,
                channel_instance_id=adapter.channel_instance_id,
                external_identity_id=envelope.external_userid,
                message=envelope.message,
                base_task_payload=envelope.task_payload,
                trace_id=envelope.message.trace_id,
                task_type=PLATFORM_INBOUND_TASK_TYPE,
                max_attempts=PLATFORM_INBOUND_MAX_ATTEMPTS,
            )
            if result.bound and result.created:
                enqueued += 1
        await db.commit()
        cursor = next_cursor
        pages += 1
        if not has_more:
            break
    return {"pages": pages, "seen": seen, "enqueued": enqueued}
