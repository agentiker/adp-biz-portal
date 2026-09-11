"""企业微信智能机器人 inline streaming turn.

Real streaming needs the agent to run where the WS socket is held, so the
gateway runs one turn inline (not via the durable worker, which can't push to a
held socket) and streams cumulative snapshots out through ``reply_stream``. It
reuses the platform's authz (identity + membership + permission), the ADP
provider and the result/evidence boundary; it records a run + assistant message
for history and the no-login result card. Duplicate callbacks are dropped by a
process-local msgid guard.

This intentionally does not create a durable inbound/reply task: delivery is the
live WS frame, so a durable reply task would have nothing to send.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Awaitable, Callable, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from core.channel_identity import resolve_active_channel_identity
from core.platform import permissions_for_role, require_permission, utc_now, PlatformContext
from core.platform_worker import (
    _execute_provider,
    _provider_agent_id,
    _result_payload,
    allowlisted_evidence,
)
from integrations.adp.provider import AgentRequest
from integrations.channels.stream_sink import SnapshotStreamSink
from integrations.channels.text_format import to_plain_text
from model.account import Account, AccountStatus
from model.platform import (
    EnterpriseStatus,
    PlatformConversation,
    PlatformEnterprise,
    PlatformEvidence,
    PlatformExecutionRun,
    PlatformMembership,
    PlatformMessage,
    PlatformStatus,
    PlatformUser,
)
from sqlalchemy import select


logger = logging.getLogger(__name__)

WECOM_BOT_UNBOUND_REPLY = "你还没有绑定业务账号。请登录官网完成渠道绑定后再试，或联系销售/客服。"

# WeCom renders a <think>…</think> block in the stream content as a collapsible,
# persistent "thinking" section (verified against openclaw-china's ws gateway).
# An empty pair is the native "思考中" placeholder shown before the answer.
WECOM_BOT_THINKING_PLACEHOLDER = "<think></think>"


def _wecom_think_render(answer: str, reasoning: str) -> str:
    """Compose the WeCom stream content: reasoning folds into a <think> block.

    ADP streams reasoning first (thought messages) then the answer (reply), so a
    growing ``<think>…</think>`` shows the thinking as it arrives and the answer
    appends below it; the thinking stays folded and persistent. With no reasoning
    it is just the answer, and with neither it is the native 思考中 placeholder.
    """
    a = to_plain_text(answer)
    r = to_plain_text(reasoning).strip()
    if r and a:
        return f"<think>{r}</think>\n{a}"
    if r:
        return f"<think>{r}</think>"
    if a:
        return a
    return WECOM_BOT_THINKING_PLACEHOLDER


class _MsgidGuard:
    """Process-local duplicate-callback guard (ws is served by one gateway)."""

    def __init__(self, *, ttl: float = 600.0, max_entries: int = 20_000) -> None:
        self._seen: dict[str, float] = {}
        self._ttl = ttl
        self._max = max_entries

    def first_seen(self, key: str) -> bool:
        now = time.monotonic()
        self._seen = {k: t for k, t in self._seen.items() if now - t < self._ttl}
        if key in self._seen:
            return False
        if len(self._seen) >= self._max:
            self._seen.pop(next(iter(self._seen)), None)
        self._seen[key] = now
        return True


_default_guard = _MsgidGuard()


async def run_wecom_bot_turn(
    sessionmaker: Callable[[], AsyncSession],
    *,
    channel: str,
    channel_instance_id: str,
    envelope: Any,
    provider: Any,
    reply_stream: Callable[..., Awaitable[Any]],
    now: float | None = None,
    guard: _MsgidGuard | None = None,
) -> Mapping[str, Any]:
    """Resolve, authorize and stream one bot turn. Returns a small status dict."""
    guard = guard or _default_guard
    message = envelope.message
    if not guard.first_seen(f"{channel_instance_id}:{message.external_message_id}"):
        return {"status": "duplicate"}

    db = sessionmaker()
    try:
        identity = await resolve_active_channel_identity(
            db, channel=channel, channel_instance_id=channel_instance_id,
            external_identity_id=envelope.from_userid,
        )
        if identity is None:
            await reply_stream(WECOM_BOT_UNBOUND_REPLY, is_final=True)
            return {"status": "unbound"}

        user = await db.get(PlatformUser, identity.UserId)
        account = await db.get(Account, user.AccountId) if user is not None else None
        if (
            user is None or account is None
            or user.Status != PlatformStatus.ACTIVE
            or account.Status in {AccountStatus.BANNED, AccountStatus.PENDING}
        ):
            await reply_stream(WECOM_BOT_UNBOUND_REPLY, is_final=True)
            return {"status": "account_inactive"}

        memberships = list((await db.execute(
            select(PlatformMembership, PlatformEnterprise)
            .join(PlatformEnterprise, PlatformEnterprise.Id == PlatformMembership.EnterpriseId)
            .where(
                PlatformMembership.UserId == user.Id,
                PlatformMembership.Active.is_(True),
                PlatformEnterprise.Status == EnterpriseStatus.ACTIVE,
            )
        )).all())
        if len(memberships) != 1:
            # A bot chat carries no enterprise selector, so an ambiguous scope
            # cannot be resolved safely.
            await reply_stream("你的账号可访问多个企业，请先在官网选择企业范围后再查询。", is_final=True)
            return {"status": "ambiguous_scope"}
        enterprise = memberships[0][1]

        context = PlatformContext(
            user=user, account=account, session=None, permissions=permissions_for_role(user.Role)
        )
        require_permission(context, "shipment.read")

        # Resolve the ADP application for this enterprise; the process-level
        # provider (from .env) is the fallback when no DB app is configured.
        from integrations.adp.registry import resolve_provider_for_enterprise

        resolved_provider = await resolve_provider_for_enterprise(
            db, enterprise, fallback=lambda: provider
        )

        query = (message.text or "").strip()
        conversation = PlatformConversation(
            AccountId=account.Id, EnterpriseId=enterprise.Id, Channel=channel,
            Title=(f"业务查询 / {query.upper()}"[:255] if query else "业务查询"),
        )
        db.add(conversation)
        await db.flush()
        run_id = f"run_{uuid.uuid4().hex}"
        request = AgentRequest(
            agent_id=_provider_agent_id(resolved_provider),
            conversation_id=str(conversation.Id),
            run_id=run_id,
            channel=channel,
            query=query,
            customer_code=str(enterprise.CustomerCode),
            trace_id=message.trace_id or "wecom-bot",
            visitor_id=f"platform:{enterprise.Id}:{account.Id}",
        )

        sink = SnapshotStreamSink(reply_stream, render=_wecom_think_render)
        await reply_stream(WECOM_BOT_THINKING_PLACEHOLDER, is_final=False)  # native 思考中 placeholder
        try:
            raw = await _execute_provider(resolved_provider, request, sink=sink)
        finally:
            await sink.close()
        result = _result_payload(raw, query=query.upper())
        evidence = allowlisted_evidence(result.get("evidence"))

        run = PlatformExecutionRun(
            ConversationId=conversation.Id, AccountId=account.Id, EnterpriseId=enterprise.Id,
            RunId=run_id, Query=query.upper()[:128], Status=str(result.get("status") or "")[:32],
            Title=str(result.get("title") or "业务查询")[:255], Summary=str(result.get("summary") or "")[:10000],
            TraceId=message.trace_id, CompletedAt=utc_now(),
        )
        db.add(run)
        await db.flush()
        for item in evidence:
            db.add(PlatformEvidence(
                ExecutionRunId=run.Id, ConversationId=conversation.Id, AccountId=account.Id,
                EnterpriseId=enterprise.Id, Label=item["label"], Value=item["value"],
                Source=item["source"], CapturedAt=utc_now(), Known=item["known"],
            ))
        db.add(PlatformMessage(
            ConversationId=conversation.Id, AccountId=account.Id, EnterpriseId=enterprise.Id,
            ExecutionRunId=run.Id, Direction="assistant", MessageType="shipment.result",
            Body=str(result.get("summary") or ""), Payload={"status": result.get("status"), "streamed": True},
            TraceId=message.trace_id,
        ))
        await db.commit()
        return {"status": "streamed", "frames": sink.frames, "conversationId": str(conversation.Id)}
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()
