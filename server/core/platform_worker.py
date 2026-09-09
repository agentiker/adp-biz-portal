"""Worker handlers for the platform inbound-message pipeline.

The handler deliberately keeps database transactions short. Identity and
scope are reloaded from the database, the execution context is committed
before the M3 call, and tool/reply records are finalized in a new transaction.
"""

from __future__ import annotations

import inspect
import logging
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import tagentic_config
from core.delivery import (
    DeliveryHandler,
    DeliveryOutcome,
    DeliveryRejectedError,
    DeliveryRetryableError,
    DeliveryTaskError,
    DeliveryUncertainError,
    enqueue_delivery_task,
)
from core.error.account import AccountUnauthorized
from core.error.platform import PlatformBadRequest, PlatformForbidden, PlatformNotFound
from core.platform import (
    PlatformContext,
    claim_tool_call,
    complete_tool_call,
    create_audit,
    issue_execution_context,
    load_execution_context,
    permissions_for_role,
    require_permission,
    utc_now,
)
from integrations.adp.provider import (
    AgentProvider,
    AgentRequest,
    AgentResponse,
    ControlledLookupAgentProvider,
    allowlisted_evidence,
)
from integrations.m3.adapter import M3LookupAdapter, M3LookupResult
from integrations.channels.base import DeliveryReceipt
from integrations.channels.stream_sink import ChannelStreamSink
from integrations.channels.text_format import to_plain_text
from model.account import Account, AccountStatus
from model.platform import (
    EnterpriseStatus,
    PlatformAuthSession,
    PlatformConversation,
    PlatformDeliveryTask,
    PlatformEvidence,
    PlatformExecutionRun,
    PlatformEnterprise,
    PlatformInboundMessage,
    PlatformMessage,
    PlatformMembership,
    PlatformStatus,
    PlatformToolCall,
    PlatformUser,
)


logger = logging.getLogger(__name__)

PLATFORM_INBOUND_TASK_TYPE = "platform.inbound.process"
PLATFORM_REPLY_TASK_TYPE = "platform.reply"
PLATFORM_INBOUND_MAX_ATTEMPTS = 3
PLATFORM_REPLY_MAX_ATTEMPTS = 3
# An answer at or under this length is fully readable in one chat message, so a
# closing "view on web" card would just be noise. Longer answers get the card:
# it links to the portal for the full, structured view and covers the case where
# the text message itself is truncated by the channel's length limit.
RESULT_CARD_MIN_CHARS = 600
_TOOL_NAME = "shipment.lookup"


def _required_uuid(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DeliveryRejectedError("invalid_task_payload")
    try:
        return str(uuid.UUID(value.strip()))
    except ValueError as exc:
        raise DeliveryRejectedError("invalid_task_payload") from exc


def _optional_uuid(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value in (None, ""):
        return None
    return _required_uuid(payload, key)


def _payload(task: PlatformDeliveryTask) -> dict[str, Any]:
    value = task.Payload
    if not isinstance(value, Mapping):
        raise DeliveryRejectedError("invalid_task_payload")
    return dict(value)


def _bounded_text(value: Any, *, limit: int, default: str | None = None) -> str | None:
    if value is None:
        return default
    if not isinstance(value, str):
        raise DeliveryRejectedError("invalid_task_payload")
    normalized = value.strip()
    if not normalized or len(normalized) > limit:
        raise DeliveryRejectedError("invalid_task_payload")
    return normalized


def _result_payload(raw: Any, *, query: str) -> dict[str, Any]:
    """Normalize adapter results without exposing provider-specific fields."""
    if isinstance(raw, AgentResponse):
        payload = raw.to_dict()
        payload["evidence"] = allowlisted_evidence(payload.get("evidence"))
        payload["auditOutcome"] = raw.audit_outcome or raw.status
        return payload
    if isinstance(raw, M3LookupResult):
        payload = raw.to_dict()
        payload["evidence"] = allowlisted_evidence(payload.get("evidence"))
        payload["auditOutcome"] = raw.audit_outcome or raw.status
        return payload
    if isinstance(raw, Mapping):
        status = raw.get("status")
        title = raw.get("title")
        summary = raw.get("summary")
        evidence = allowlisted_evidence(raw.get("evidence", []))
        if not isinstance(status, str) or not status.strip():
            status = "upstream_error"
        if not isinstance(title, str) or not title.strip():
            title = "业务系统暂时无法响应"
        if not isinstance(summary, str) or not summary.strip():
            summary = "业务系统暂时不可用，请稍后重试。平台没有使用未核实的数据替代结果。"
        if not isinstance(evidence, list):
            evidence = []
        return {
            "status": status.strip()[:64],
            "query": query,
            "title": title.strip()[:255],
            "summary": summary.strip()[:2000],
            "evidence": evidence,
            "traceId": str(raw.get("traceId") or "")[:64],
            "auditOutcome": str(raw.get("auditOutcome") or status).strip()[:64],
        }
    return {
        "status": "upstream_error",
        "query": query,
        "title": "业务系统暂时无法响应",
        "summary": "业务系统暂时不可用，请稍后重试。平台没有使用未核实的数据替代结果。",
        "evidence": [],
        "traceId": "",
        "auditOutcome": "upstream_error",
    }


def _allowlisted_evidence(raw: Any) -> list[dict[str, Any]]:
    """Backward-compatible alias for the provider-owned evidence boundary."""
    return allowlisted_evidence(raw)


def _upstream_error_result(query: str) -> dict[str, Any]:
    return {
        "status": "upstream_error",
        "query": query,
        "title": "M3 暂时无法响应",
        "summary": "业务系统暂时不可用，请稍后重试。平台没有使用未核实的数据替代结果。",
        "evidence": [],
        "traceId": "",
        "auditOutcome": "upstream_error",
    }


def _provider_capabilities(provider: Any) -> frozenset[str]:
    """Read a provider capability declaration and fail closed on bad contracts."""
    try:
        capabilities = getattr(provider, "capabilities", None)
    except Exception as exc:
        raise DeliveryRejectedError("provider_capabilities_invalid") from exc
    if isinstance(capabilities, (str, bytes)) or capabilities is None:
        raise DeliveryRejectedError("provider_capabilities_invalid")
    try:
        values = tuple(capabilities)
    except TypeError as exc:
        raise DeliveryRejectedError("provider_capabilities_invalid") from exc
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise DeliveryRejectedError("provider_capabilities_invalid")
    return frozenset(item.strip() for item in values)


def _provider_agent_id(provider: Any) -> str:
    """Use only a server-created provider mapping for execution context IDs."""
    value = getattr(provider, "agent_id", None)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
        return "platform-default"
    return value.strip()


def _resolve_agent_provider(provider: Any, adapter: Any = None) -> AgentProvider:
    """Resolve and validate the provider before any execution record is created."""
    resolved = provider
    if resolved is None:
        lookup_adapter = adapter
        if lookup_adapter is None:
            lookup_adapter = M3LookupAdapter(
                use_mock=bool(tagentic_config.M3_USE_MOCK),
                base_url=tagentic_config.M3_BASE_URL,
                timeout_seconds=tagentic_config.M3_TIMEOUT_SECONDS,
            )
        resolved = ControlledLookupAgentProvider(lookup_adapter)
    try:
        execute = getattr(resolved, "execute", None)
    except Exception as exc:
        raise DeliveryRejectedError("provider_execute_invalid") from exc
    if not callable(execute):
        raise DeliveryRejectedError("provider_execute_invalid")
    if _TOOL_NAME not in _provider_capabilities(resolved):
        raise DeliveryRejectedError("provider_capability_missing")
    return resolved


async def _mark_rejected(
    sessionmaker: Callable[[], AsyncSession],
    *,
    inbound_id: str | None,
    trace_id: str,
    error_code: str,
    account_id: str | None = None,
) -> None:
    """Persist a terminal identity/scope rejection in its own transaction."""
    if inbound_id is None:
        return
    db = sessionmaker()
    try:
        inbound = await db.get(PlatformInboundMessage, inbound_id)
        if inbound is None:
            return
        inbound.Status = "rejected"
        db.add(inbound)
        await create_audit(
            db,
            actor_account_id=account_id,
            action="platform.inbound.reject",
            target_type="platform_inbound_message",
            target_id=str(inbound.Id),
            trace_id=trace_id,
            outcome="rejected",
            metadata={"errorCode": error_code},
        )
        await db.commit()
    finally:
        await db.close()


def _rejection_code(exc: Exception) -> str:
    if isinstance(exc, AccountUnauthorized):
        return "identity_invalid"
    if isinstance(exc, PlatformForbidden):
        return "forbidden"
    if isinstance(exc, PlatformNotFound):
        return "scope_not_found"
    if isinstance(exc, PlatformBadRequest):
        return "invalid_scope"
    if isinstance(exc, DeliveryTaskError):
        return "invalid_task_payload"
    return "task_rejected"


def _provider_accepts_sink(provider: Any) -> bool:
    """Report whether a provider implements the streaming contract.

    The sink is an optional extension, so a provider written against the
    original ``execute(request)`` signature must keep working rather than
    failing every message with a TypeError.
    """
    execute = getattr(provider, "execute", None)
    if execute is None:
        return False
    try:
        parameters = inspect.signature(execute).parameters
    except (TypeError, ValueError):
        return False
    if "sink" in parameters:
        return True
    return any(item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values())


async def _execute_provider(provider: Any, request: AgentRequest, *, sink: Any = None) -> Any:
    if sink is not None and _provider_accepts_sink(provider):
        return await provider.execute(request, sink=sink)
    return await provider.execute(request)


async def _build_stream_sink(
    sender: Any,
    *,
    channel: str,
    channel_instance_id: str,
    external_conversation_id: str,
    inbound_id: str,
    trace_id: str,
) -> Any:
    """Build a streaming sink when the channel can push messages mid-run.

    The website channel is read back by the browser, so it needs no push. A
    channel without a configured sender streams nothing and still receives the
    single validated reply from the reply task.
    """
    if channel == "web" or not channel_instance_id:
        return None
    resolved = await _resolve_channel_sender(
        sender, channel=channel, channel_instance_id=channel_instance_id
    )
    if resolved is None:
        return None
    if not getattr(resolved, "supports_incremental_stream", False):
        # A channel that can only send discrete messages (WeChat Official
        # Account) delivers one complete answer from the reply task instead of
        # mid-run chunks, so nothing is streamed here. Real streaming is opt-in
        # per sender (e.g. the WeCom smart-bot stream protocol) and belongs to
        # M3-WECOM-01.
        return None
    return ChannelStreamSink(
        resolved,
        open_id_payload={
            "channel": channel,
            "channelInstanceId": channel_instance_id,
            "externalConversationId": external_conversation_id,
            "traceId": trace_id,
        },
        idempotency_prefix=f"platform-stream:{inbound_id}",
    )


async def process_platform_inbound_task(
    sessionmaker: Callable[[], AsyncSession],
    task: PlatformDeliveryTask,
    *,
    adapter: Any = None,
    agent_provider: AgentProvider | Any = None,
    reply_sender: Any = None,
) -> DeliveryOutcome:
    """Process one normalized inbound message through the Agent provider.

    ``reply_sender`` enables streaming: when the channel can push messages, the
    upstream agent text is forwarded as it arrives instead of waiting for the
    whole answer. What was streamed is recorded on the reply payload so the
    final reply task does not repeat it.
    """
    inbound_id: str | None = None
    trace_id: str | None = None
    account_id: str | None = None
    conversation_id_value: str | None = None
    run_id: str | None = None
    streamed_chunks = 0
    streamed_sequence = 0
    db = sessionmaker()
    inbound: PlatformInboundMessage | None = None
    try:
        payload = _payload(task)
        inbound_id = _required_uuid(payload, "inboundMessageId")
        platform_user_id = _required_uuid(payload, "platformUserId")
        platform_session_id = _optional_uuid(payload, "platformSessionId")
        enterprise_id = _optional_uuid(payload, "enterpriseId")
        conversation_id = _optional_uuid(payload, "conversationId")
        channel = _bounded_text(payload.get("channel"), limit=32, default="web") or "web"
        trace_id = _bounded_text(payload.get("traceId"), limit=64, default=None)
        run_id = _bounded_text(payload.get("runId"), limit=64, default=None) or f"run_{inbound_id.replace('-', '')}"
        inbound = await db.get(PlatformInboundMessage, inbound_id)
        if inbound is None:
            raise DeliveryRejectedError("inbound_not_found")
        trace_id = trace_id or inbound.TraceId
        if not isinstance(trace_id, str) or not trace_id.strip():
            raise DeliveryRejectedError("invalid_trace_id")

        # A completed inbound message is safe to acknowledge again. This is
        # the fast path after a worker lease is recovered.
        existing_reply = (
            await db.execute(
                select(PlatformDeliveryTask).where(
                    PlatformDeliveryTask.DeduplicationKey == f"platform-reply:{inbound_id}"
                )
            )
        ).scalar_one_or_none()
        if inbound.Status == "processed" and existing_reply is not None:
            # This retry path does not enter the later transactions, so close
            # the validation session explicitly before returning.
            await db.close()
            return DeliveryOutcome({"status": "already_processed", "replyTaskId": str(existing_reply.Id)})
        if inbound.Status == "rejected":
            raise DeliveryRejectedError("inbound_rejected")

        user = await db.get(PlatformUser, platform_user_id)
        account = await db.get(Account, user.AccountId) if user is not None else None
        account_id = str(account.Id) if account is not None else None
        if (
            user is None
            or account is None
            or user.Status != PlatformStatus.ACTIVE
            or account.Status in {AccountStatus.BANNED, AccountStatus.PENDING}
            or str(user.AccountId) != str(account.Id)
        ):
            raise AccountUnauthorized("账号已停用")

        memberships = list(
            (
                await db.execute(
                    select(PlatformMembership, PlatformEnterprise)
                    .join(PlatformEnterprise, PlatformEnterprise.Id == PlatformMembership.EnterpriseId)
                    .where(
                        PlatformMembership.UserId == user.Id,
                        PlatformMembership.Active.is_(True),
                        PlatformEnterprise.Status == EnterpriseStatus.ACTIVE,
                    )
                )
            ).all()
        )
        if enterprise_id is not None:
            enterprise = next((item[1] for item in memberships if str(item[1].Id) == enterprise_id), None)
            if enterprise is None:
                raise PlatformForbidden("当前账号没有可访问的企业范围")
        else:
            if len(memberships) != 1:
                raise PlatformForbidden("需要明确企业范围")
            enterprise = memberships[0][1]

        # A browser message carries the login session that produced it. A
        # channel message is authorized by its confirmed channel identity plus
        # the memberships resolved above, so it has no session to validate; a
        # stale browser session must never be borrowed to authorize it.
        session = None
        if platform_session_id is not None:
            session = await db.get(PlatformAuthSession, platform_session_id)
            if (
                session is None
                or str(session.AccountId) != str(account.Id)
                or session.RevokedAt is not None
                or session.ExpiresAt <= utc_now()
            ):
                raise AccountUnauthorized("平台登录态已失效")

        context = PlatformContext(
            user=user,
            account=account,
            session=session,
            permissions=permissions_for_role(user.Role),
        )
        require_permission(context, "shipment.read")
        provider = _resolve_agent_provider(agent_provider, adapter)

        query = (inbound.Text or "").strip()
        conversation = None
        if conversation_id is not None:
            conversation = (
                await db.execute(
                    select(PlatformConversation).where(
                        PlatformConversation.Id == conversation_id,
                        PlatformConversation.AccountId == account.Id,
                        PlatformConversation.EnterpriseId == enterprise.Id,
                    )
                )
            ).scalar_one_or_none()
            if conversation is None:
                raise PlatformNotFound("会话不存在或无权访问")
        else:
            conversation = PlatformConversation(
                AccountId=account.Id,
                EnterpriseId=enterprise.Id,
                Channel=channel,
                Title=f"业务查询 / {query.upper()}"[:255] if query else "业务查询",
            )
            db.add(conversation)
            await db.flush()
        conversation_id_value = str(conversation.Id)
        conversation.LastActiveAt = utc_now()
        db.add(conversation)

        # The run and inbound message are created before the provider call so
        # the Portal can show an in-progress execution and recover it after a
        # worker restart.  The inbound ID is stored in the message payload to
        # make retries idempotent without trusting browser-provided fields.
        execution_run = (
            await db.execute(
                select(PlatformExecutionRun).where(
                    PlatformExecutionRun.RunId == run_id,
                    PlatformExecutionRun.AccountId == account.Id,
                    PlatformExecutionRun.EnterpriseId == enterprise.Id,
                    PlatformExecutionRun.ConversationId == conversation.Id,
                )
            )
        ).scalar_one_or_none()
        if execution_run is None:
            execution_run = PlatformExecutionRun(
                ConversationId=conversation.Id,
                AccountId=account.Id,
                EnterpriseId=enterprise.Id,
                RunId=run_id,
                Query=query.upper()[:128],
                Status="running",
                Title="业务查询",
                Summary="",
                TraceId=trace_id,
            )
            db.add(execution_run)
            await db.flush()
        else:
            if execution_run.Query != query.upper()[:128]:
                raise DeliveryRejectedError("run_scope_mismatch")
            execution_run.Status = "running"
            execution_run.CompletedAt = None
            execution_run.TraceId = trace_id
            db.add(execution_run)

        inbound_message = (
            await db.execute(
                select(PlatformMessage).where(
                    PlatformMessage.ExecutionRunId == execution_run.Id,
                    PlatformMessage.Direction == "inbound",
                )
            )
        ).scalar_one_or_none()
        if inbound_message is None:
            db.add(PlatformMessage(
                ConversationId=conversation.Id,
                AccountId=account.Id,
                EnterpriseId=enterprise.Id,
                ExecutionRunId=execution_run.Id,
                Direction="inbound",
                MessageType=inbound.MessageType or "text",
                Body=query,
                Payload={"inboundMessageId": inbound_id, "channel": channel},
                TraceId=trace_id,
            ))

        raw_context_token, execution = await issue_execution_context(
            db,
            platform_context=context,
            agent_id=_provider_agent_id(provider),
            channel=channel,
            enterprise_id=str(enterprise.Id),
            conversation_id=str(conversation.Id),
            run_id=run_id,
            ttl_seconds=tagentic_config.ADP_EXECUTION_CONTEXT_TTL_SECONDS,
        )
        # Persist server-generated scope before the provider call. A retry or
        # process restart must resume the same conversation/run instead of
        # creating a second run with the same idempotency key.
        task_row = await db.get(PlatformDeliveryTask, task.Id)
        if task_row is not None:
            persisted_payload = dict(payload)
            persisted_payload["conversationId"] = conversation_id_value
            persisted_payload["runId"] = run_id
            persisted_payload["agentId"] = execution.AgentId
            task_row.Payload = persisted_payload
            db.add(task_row)
        await db.commit()
    except DeliveryRejectedError as exc:
        await db.rollback()
        await db.close()
        await _mark_rejected(
            sessionmaker,
            inbound_id=inbound_id,
            trace_id=trace_id or "platform-worker",
            error_code=exc.error_code,
            account_id=account_id,
        )
        raise
    except (AccountUnauthorized, PlatformBadRequest, PlatformForbidden, PlatformNotFound, DeliveryTaskError) as exc:
        await db.rollback()
        await db.close()
        code = _rejection_code(exc)
        await _mark_rejected(
            sessionmaker,
            inbound_id=inbound_id,
            trace_id=trace_id or "platform-worker",
            error_code=code,
            account_id=account_id,
        )
        raise DeliveryRejectedError(code) from exc
    except Exception:
        await db.rollback()
        await db.close()
        raise
    else:
        await db.close()

    # The values below have passed validation before the first transaction
    # committed. Keeping this guard explicit also satisfies static type
    # checkers without weakening the runtime contract.
    if inbound_id is None or inbound is None:
        raise DeliveryRejectedError("invalid_task_payload")

    request_id = f"platform-inbound:{inbound_id}"
    claim_db = sessionmaker()
    call: PlatformToolCall | None = None
    try:
        loaded_execution = await load_execution_context(
            claim_db,
            token=raw_context_token,
            tool_name=_TOOL_NAME,
            request_id=request_id,
        )
        call = await claim_tool_call(
            claim_db,
            execution=loaded_execution,
            tool_name=_TOOL_NAME,
            request_id=request_id,
            trace_id=trace_id or "platform-worker",
            query=(inbound.Text or "").strip(),
        )
        await claim_db.commit()
    except (AccountUnauthorized, PlatformBadRequest, PlatformForbidden, PlatformNotFound, DeliveryTaskError) as exc:
        await claim_db.rollback()
        await claim_db.close()
        code = _rejection_code(exc)
        await _mark_rejected(
            sessionmaker,
            inbound_id=inbound_id,
            trace_id=trace_id or "platform-worker",
            error_code=code,
            account_id=account_id,
        )
        raise DeliveryRejectedError(code) from exc
    except Exception:
        await claim_db.rollback()
        await claim_db.close()
        raise
    else:
        await claim_db.close()

    query = (inbound.Text or "").strip()
    try:
        provider_request = AgentRequest(
            agent_id=loaded_execution.context.AgentId,
            conversation_id=str(loaded_execution.context.ConversationId or conversation_id_value),
            run_id=loaded_execution.context.RunId,
            channel=loaded_execution.context.Channel,
            query=query,
            customer_code=str(enterprise.CustomerCode),
            trace_id=trace_id or "platform-worker",
            visitor_id=f"platform:{enterprise.Id}:{account.Id}",
        )
        sink = await _build_stream_sink(
            reply_sender,
            channel=channel,
            channel_instance_id=inbound.ChannelInstanceId,
            external_conversation_id=inbound.ExternalConversationId,
            inbound_id=inbound_id,
            trace_id=trace_id or "platform-worker",
        )
        raw_result = await _execute_provider(provider, provider_request, sink=sink)
        result = _result_payload(raw_result, query=query.upper())
        if sink is not None:
            streamed_chunks = sink.sent_chunks
            streamed_sequence = sink.sequence
    except DeliveryRetryableError:
        # A known transient M3 failure may retry the business task within its
        # bounded attempt count. The tool request ID remains stable, so a
        # worker restart cannot create a second tool call for the same run.
        raise
    except Exception:
        result = _upstream_error_result(query.upper())

    final_db = sessionmaker()
    try:
        final_call = await final_db.get(PlatformToolCall, call.Id if call is not None else None)
        final_inbound = await final_db.get(PlatformInboundMessage, inbound_id)
        final_run = (
            await final_db.execute(
                select(PlatformExecutionRun).where(
                    PlatformExecutionRun.RunId == run_id,
                    PlatformExecutionRun.AccountId == account_id,
                    PlatformExecutionRun.EnterpriseId == str(enterprise.Id),
                    PlatformExecutionRun.ConversationId == conversation_id_value,
                )
            )
        ).scalar_one_or_none()
        if final_call is None or final_inbound is None or final_run is None:
            raise DeliveryTaskError("编排记录不存在")
        evidence = _allowlisted_evidence(result.get("evidence"))
        await complete_tool_call(
            final_db,
            call=final_call,
            status="completed",
            outcome=str(result.get("auditOutcome") or result.get("status") or "upstream_error"),
            evidence=evidence,
        )
        final_run.Status = str(result.get("status") or "upstream_error")[:32]
        final_run.Title = str(result.get("title") or "业务查询")[:255]
        final_run.Summary = str(result.get("summary") or "")[:10000]
        final_run.TraceId = trace_id
        final_run.CompletedAt = utc_now()
        final_db.add(final_run)
        await final_db.execute(
            delete(PlatformEvidence).where(PlatformEvidence.ExecutionRunId == final_run.Id)
        )
        for item in evidence:
            final_db.add(PlatformEvidence(
                ExecutionRunId=final_run.Id,
                ConversationId=final_run.ConversationId,
                AccountId=final_run.AccountId,
                EnterpriseId=final_run.EnterpriseId,
                Label=item["label"],
                Value=item["value"],
                Source=item["source"],
                CapturedAt=utc_now(),
                Known=item["known"],
            ))
        assistant_message = (
            await final_db.execute(
                select(PlatformMessage).where(
                    PlatformMessage.ExecutionRunId == final_run.Id,
                    PlatformMessage.Direction == "assistant",
                )
            )
        ).scalar_one_or_none()
        assistant_payload = {
            "status": result.get("status"),
            "title": result.get("title"),
            "query": result.get("query") or query.upper(),
            "evidence": evidence,
            "providerTraceId": result.get("traceId") or "",
        }
        if assistant_message is None:
            final_db.add(PlatformMessage(
                ConversationId=final_run.ConversationId,
                AccountId=final_run.AccountId,
                EnterpriseId=final_run.EnterpriseId,
                ExecutionRunId=final_run.Id,
                Direction="assistant",
                MessageType="shipment.result",
                Body=final_run.Summary,
                Payload=assistant_payload,
                TraceId=trace_id,
            ))
        else:
            assistant_message.Body = final_run.Summary
            assistant_message.Payload = assistant_payload
            assistant_message.TraceId = trace_id
            final_db.add(assistant_message)
        final_inbound.Status = "processed"
        final_db.add(final_inbound)
        reply_payload = {
            "inboundMessageId": inbound_id,
            "accountId": account_id,
            "platformUserId": platform_user_id,
            "platformSessionId": str(session.Id) if session is not None else None,
            "enterpriseId": str(enterprise.Id),
            "conversationId": conversation_id_value,
            "runId": run_id,
            "channel": channel,
            "channelInstanceId": inbound.ChannelInstanceId,
            "externalConversationId": inbound.ExternalConversationId,
            "externalMessageId": inbound.ExternalMessageId,
            # Carried from ingest so the sender can refuse a reply the channel
            # protocol would no longer accept instead of guessing at send time.
            "replyWindowExpiresAt": (
                final_inbound.ReplyWindowExpiresAt.isoformat()
                if final_inbound.ReplyWindowExpiresAt is not None
                else None
            ),
            "traceId": trace_id,
            "status": result.get("status"),
            "title": result.get("title"),
            "summary": result.get("summary"),
            "evidence": evidence,
            "providerTraceId": result.get("traceId") or "",
            # Stable across worker restarts and safe for an upstream sender to
            # use as its message/idempotency key when delivery is retried.
            "deliveryIdempotencyKey": f"platform-reply:{inbound_id}",
            # Streaming already showed the customer this answer. The reply task
            # must not send it a second time, but it still re-checks
            # authorization and records delivery.
            "streamedChunks": streamed_chunks,
            "streamedSequence": streamed_sequence,
        }
        reply_task, reply_created = await enqueue_delivery_task(
            final_db,
            task_type=PLATFORM_REPLY_TASK_TYPE,
            deduplication_key=f"platform-reply:{inbound_id}",
            conversation_key=f"{inbound.ChannelInstanceId}:{inbound.ExternalConversationId}",
            payload=reply_payload,
            max_attempts=PLATFORM_REPLY_MAX_ATTEMPTS,
        )
        await create_audit(
            final_db,
            actor_account_id=account_id,
            action="platform.inbound.process",
            target_type="platform_inbound_message",
            target_id=inbound_id,
            trace_id=trace_id,
            outcome=str(result.get("auditOutcome") or result.get("status") or "upstream_error"),
            metadata={
                "tool": _TOOL_NAME,
                "toolCallId": str(final_call.Id),
                "replyTaskId": str(reply_task.Id),
                "replyCreated": reply_created,
                "enterpriseId": str(enterprise.Id),
                "runId": run_id,
                "evidenceCount": len(evidence),
            },
        )
        await final_db.commit()
    except Exception:
        await final_db.rollback()
        raise
    finally:
        await final_db.close()

    return DeliveryOutcome({
        "status": result.get("status"),
        "replyTaskId": str(reply_task.Id),
        "conversationId": conversation_id_value,
        "runId": run_id,
        "traceId": trace_id,
    })


def _reply_window_expired(value: Any, *, now: datetime) -> bool:
    """Return True when a recorded reply deadline has already passed."""
    if value is None:
        return False
    if isinstance(value, datetime):
        deadline = value
    elif isinstance(value, str) and value.strip():
        try:
            deadline = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            # An unreadable deadline is treated as expired: sending into a
            # window that cannot be verified would risk a provider rejection
            # that the platform reports as success.
            return True
    else:
        return True
    if deadline.tzinfo is not None:
        deadline = deadline.astimezone(UTC).replace(tzinfo=None)
    return deadline <= now


async def _reply_authorization_error(
    db: AsyncSession,
    *,
    inbound_id: str,
    account_id: str,
    platform_user_id: str,
    platform_session_id: str | None,
    enterprise_id: str,
    reply_window_expires_at: Any = None,
) -> str | None:
    """Re-check one queued reply against current identity, scope and window."""
    inbound = await db.get(PlatformInboundMessage, inbound_id)
    user = await db.get(PlatformUser, platform_user_id)
    account = await db.get(Account, account_id)
    enterprise = await db.get(PlatformEnterprise, enterprise_id)
    # A channel reply has no browser session; only a session-bound reply is
    # invalidated by that session ending.
    session = (
        await db.get(PlatformAuthSession, platform_session_id)
        if platform_session_id is not None
        else None
    )
    membership = None
    if user is not None and enterprise is not None:
        membership = (
            await db.execute(
                select(PlatformMembership).where(
                    PlatformMembership.UserId == user.Id,
                    PlatformMembership.EnterpriseId == enterprise.Id,
                    PlatformMembership.Active.is_(True),
                )
            )
        ).scalar_one_or_none()

    if inbound is None or inbound.Status != "processed":
        return "inbound_not_processed"
    if (
        user is None
        or account is None
        or str(user.AccountId) != str(account.Id)
        or user.Status != PlatformStatus.ACTIVE
        or account.Status in {AccountStatus.BANNED, AccountStatus.PENDING}
    ):
        return "authorization_revoked"
    if platform_session_id is not None and (
        session is None
        or str(session.AccountId) != str(account.Id)
        or session.RevokedAt is not None
        or session.ExpiresAt <= utc_now()
    ):
        return "authorization_revoked"
    if enterprise is None or enterprise.Status != EnterpriseStatus.ACTIVE or membership is None:
        return "authorization_revoked"
    if (
        "shipment.read" not in permissions_for_role(user.Role)
        or "shipment.read" not in permissions_for_role(membership.MembershipRole)
    ):
        return "authorization_revoked"
    deadline = reply_window_expires_at
    if deadline is None:
        deadline = inbound.ReplyWindowExpiresAt
    if _reply_window_expired(deadline, now=utc_now()):
        return "reply_window_expired"
    return None


async def _resolve_channel_sender(
    sender: Any,
    *,
    channel: str,
    channel_instance_id: str | None,
) -> Any:
    """Select the sender that owns one channel instance.

    Each channel speaks its own send protocol, so a deployment with several
    channels registers a mapping keyed by ``channel`` or ``channel:instance``,
    or a resolver that loads senders from stored credentials on demand. A single
    sender is accepted only when it does not declare a different channel, so a
    WeChat reply can never be handed to a 企微 sender.
    """
    if sender is None:
        return None
    if getattr(sender, "is_channel_sender_resolver", False):
        return await sender.resolve(channel=channel, channel_instance_id=channel_instance_id)
    if isinstance(sender, Mapping):
        if channel_instance_id is not None:
            scoped = sender.get(f"{channel}:{channel_instance_id}")
            if scoped is not None:
                return scoped
        return sender.get(channel)
    declared = getattr(sender, "channel", None)
    if isinstance(declared, str) and declared != channel:
        return None
    return sender


def _portal_result_url(payload: Mapping[str, Any]) -> str | None:
    """Build a portal link for a channel message, or None when unavailable.

    Without a configured public origin there is no link a customer could open,
    so the card is skipped rather than sent with an unreachable URL.
    """
    base = str(tagentic_config.PLATFORM_PUBLIC_BASE_URL or "").strip().rstrip("/")
    conversation_id = payload.get("conversationId")
    if not base or not isinstance(conversation_id, str) or not conversation_id.strip():
        return None
    if not base.startswith(("https://", "http://")):
        return None
    return f"{base}/#/portal/lookup?conversationId={conversation_id.strip()}"


async def _send_result_card(sender: Any, *, payload: Mapping[str, Any]) -> str:
    """Send the closing rich card when the channel and configuration allow it.

    A card failure never fails the reply: the answer itself already reached the
    customer, so this only reports what happened.
    """
    send_card = getattr(sender, "send_result_card", None) if sender is not None else None
    if send_card is None:
        return "unsupported"
    url = _portal_result_url(payload)
    if url is None:
        return "skipped_no_public_url"
    title = str(payload.get("title") or "业务查询结果").strip() or "业务查询结果"
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        return "skipped_no_summary"
    # The card is the overflow affordance, not a decoration on every reply. A
    # short answer is already shown in full as the text message, so measuring
    # the reader-visible (plain-text) length decides whether a web view helps.
    if len(to_plain_text(summary)) <= RESULT_CARD_MIN_CHARS:
        return "skipped_short_answer"
    try:
        receipt = await send_card(
            payload=payload,
            title=title,
            description=summary,
            url=url,
        )
    except Exception as exc:
        logger.warning("result card send failed: %s", type(exc).__name__)
        return "failed"
    status = getattr(receipt, "status", None)
    return str(status) if status else "unknown"


async def process_platform_reply_task(
    sessionmaker: Callable[[], AsyncSession],
    task: PlatformDeliveryTask,
    *,
    sender: Any = None,
) -> DeliveryOutcome:
    """Deliver one validated reply without re-running the business query.

    The website channel is delivered by the persisted Portal message.  Real
    channel senders are deliberately opt-in; until a protocol adapter is
    configured, marking a WeChat/企微 reply as delivered would be false.
    """
    payload = _payload(task)
    inbound_id = _required_uuid(payload, "inboundMessageId")
    channel = _bounded_text(payload.get("channel"), limit=32, default="web") or "web"
    channel_instance_id = _bounded_text(payload.get("channelInstanceId"), limit=128, default=None)
    trace_id = _bounded_text(payload.get("traceId"), limit=64, default="platform-reply") or "platform-reply"
    delivery_key = _bounded_text(
        payload.get("deliveryIdempotencyKey"),
        limit=255,
        default=f"platform-reply:{inbound_id}",
    ) or f"platform-reply:{inbound_id}"

    # Every reply payload is stamped with the identity and scope used for the
    # original query, and it is re-validated immediately before delivery so an
    # already queued reply cannot outlive a password reset, disable, or
    # enterprise/role change.
    account_id = _required_uuid(payload, "accountId")
    platform_user_id = _required_uuid(payload, "platformUserId")
    platform_session_id = _optional_uuid(payload, "platformSessionId")
    enterprise_id = _required_uuid(payload, "enterpriseId")
    db = sessionmaker()
    try:
        authorization_error = await _reply_authorization_error(
            db,
            inbound_id=inbound_id,
            account_id=account_id,
            platform_user_id=platform_user_id,
            platform_session_id=platform_session_id,
            enterprise_id=enterprise_id,
            reply_window_expires_at=payload.get("replyWindowExpiresAt"),
        )
        if authorization_error is not None:
            await create_audit(
                db,
                actor_account_id=account_id,
                action="platform.reply.reject",
                target_type="platform_inbound_message",
                target_id=inbound_id,
                trace_id=trace_id,
                outcome="rejected",
                metadata={"errorCode": authorization_error, "channel": channel},
            )
            await db.commit()
            raise DeliveryRejectedError(authorization_error)
    except DeliveryRejectedError:
        raise
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()

    streamed_chunks = payload.get("streamedChunks")
    already_streamed = isinstance(streamed_chunks, int) and streamed_chunks > 0

    if channel != "web":
        sender = await _resolve_channel_sender(
            sender,
            channel=channel,
            channel_instance_id=channel_instance_id,
        )

    if channel != "web" and already_streamed:
        # The answer already reached the customer as a stream. Re-sending the
        # text would duplicate what they just read; a closing card adds the
        # structured record and a link to the full evidence.
        card = await _send_result_card(sender, payload=payload)
        return DeliveryOutcome({
            "status": "delivered",
            "channel": channel,
            "deliveryMode": "streamed",
            "streamedChunks": streamed_chunks,
            "resultCard": card,
        })

    if channel != "web":
        if sender is None:
            raise DeliveryRejectedError("channel_sender_not_configured")
        send = getattr(sender, "send", None)
        if send is None and callable(sender):
            send = sender
        if send is None:
            raise DeliveryRejectedError("channel_sender_invalid")
        try:
            # The sender receives a stable key so a retry after a process
            # restart can be deduplicated by the upstream provider.
            send_payload = dict(payload)
            send_payload["deliveryIdempotencyKey"] = delivery_key
            result = send(payload=send_payload)
            if hasattr(result, "__await__"):
                result = await result
        except (DeliveryRetryableError, DeliveryUncertainError, DeliveryRejectedError):
            raise
        except Exception as exc:
            raise DeliveryUncertainError("channel_send_result_unknown") from exc
        if isinstance(result, DeliveryReceipt):
            if result.uncertain or result.status == "uncertain":
                raise DeliveryUncertainError("channel_send_result_unknown")
            if result.status == "failed":
                raise DeliveryRejectedError(str((result.metadata or {}).get("reason") or "channel_send_rejected"))
        # The complete answer was delivered as one message; a closing card adds
        # the structured record and a link to the full evidence. A card failure
        # never fails the reply, mirroring the streamed path.
        card = await _send_result_card(sender, payload=payload)
        return DeliveryOutcome({
            "status": "delivered",
            "channel": channel,
            "deliveryMode": "single",
            "providerResult": result if isinstance(result, Mapping) else {},
            "resultCard": card,
        })

    db = sessionmaker()
    try:
        inbound = await db.get(PlatformInboundMessage, inbound_id)
        if inbound is None or inbound.Status != "processed":
            raise DeliveryRejectedError("inbound_not_processed")
        account_id = payload.get("accountId")
        await create_audit(
            db,
            actor_account_id=account_id if isinstance(account_id, str) else None,
            action="platform.reply.deliver",
            target_type="platform_inbound_message",
            target_id=inbound_id,
            trace_id=trace_id,
            outcome="delivered",
            metadata={"channel": channel, "deliveryMode": "portal_query"},
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()
    return DeliveryOutcome({
        "status": "delivered",
        "channel": channel,
        "deliveryMode": "portal_query",
        "inboundMessageId": inbound_id,
    })


def build_platform_delivery_handlers(
    sessionmaker: Callable[[], AsyncSession],
    *,
    adapter_factory: Callable[[], Any] | Any = None,
    agent_provider_factory: Callable[[], AgentProvider] | AgentProvider | None = None,
    reply_sender_factory: Callable[[], Any] | Any = None,
) -> Mapping[str, DeliveryHandler]:
    """Build handlers for a worker process without sharing request sessions.

    ``reply_sender_factory`` may return a single sender or a mapping keyed by
    ``channel`` or ``channel:instance``. Multi-channel deployments need the
    mapping form: one sender per channel protocol, resolved per reply.
    """

    async def inbound_handler(task: PlatformDeliveryTask) -> DeliveryOutcome:
        adapter = adapter_factory() if callable(adapter_factory) else adapter_factory
        provider = (
            agent_provider_factory() if callable(agent_provider_factory) else agent_provider_factory
        )
        sender = reply_sender_factory() if callable(reply_sender_factory) else reply_sender_factory
        return await process_platform_inbound_task(
            sessionmaker,
            task,
            adapter=adapter,
            agent_provider=provider,
            reply_sender=sender,
        )

    async def reply_handler(task: PlatformDeliveryTask) -> DeliveryOutcome:
        sender = reply_sender_factory() if callable(reply_sender_factory) else reply_sender_factory
        return await process_platform_reply_task(sessionmaker, task, sender=sender)

    return {
        PLATFORM_INBOUND_TASK_TYPE: inbound_handler,
        PLATFORM_REPLY_TASK_TYPE: reply_handler,
    }
