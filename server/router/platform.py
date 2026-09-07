"""Unified platform APIs.

These routes are intentionally separate from the legacy ADP compatibility
surface. Identity, enterprise scope, permissions, and conversation ownership
are all derived from the revocable platform session.
"""

from __future__ import annotations

import logging
import json as stdlib_json
import uuid
from functools import wraps
from typing import Any

from sanic import json, text
from sanic.request.types import Request
from sanic.views import HTTPMethodView
from sqlalchemy import func, select

from app_factory import TAgenticApp
from config import tagentic_config
from core.error.account import AccountAuthenticationError, AccountUnauthorized
from core.error.platform import PlatformBadRequest, PlatformForbidden, PlatformNotFound
from core.error.server import RateLimit
from core.platform import (
    PlatformContext,
    claim_tool_call,
    complete_tool_call,
    authenticate_platform,
    create_admin_adp_context_token,
    create_audit,
    create_enterprise,
    create_platform_user,
    generate_initial_password,
    get_enterprise_for_user,
    get_enterprises_for_user,
    get_platform_config_state,
    is_adp_service_token_valid,
    issue_execution_context,
    load_execution_context,
    load_platform_context,
    permissions_for_role,
    require_permission,
    revoke_account_execution_contexts,
    revoke_account_delivery_tasks,
    revoke_account_sessions,
    rollback_platform_config,
    save_platform_config_draft,
    publish_platform_config,
    serialize_enterprise,
    serialize_user,
    update_platform_user_access,
    _new_salt,
    utc_now,
)
from core.delivery import InboundMessageInput, record_inbound_message
from core.channel_credentials import (
    ChannelCredentialError,
    decrypt_credential,
    encrypt_credential,
    load_active_channel_credentials,
    load_active_channel_instance_credential,
    serialize_credential,
)
from core.channel_identity import (
    begin_channel_identity_binding,
    confirm_channel_identity_binding,
    external_identity_fingerprint,
    revoke_channel_identity,
    revoke_account_channel_identities,
    serialize_channel_identity,
    resolve_active_channel_identity,
)
from core.platform_worker import PLATFORM_INBOUND_MAX_ATTEMPTS, PLATFORM_INBOUND_TASK_TYPE
from integrations.m3.adapter import M3LookupAdapter, M3LookupResult
from integrations.channels.registry import ChannelRegistryError, register_default_adapters
from integrations.channels.wechat_official_account import (
    WECHAT_OFFICIAL_ACCOUNT,
    WechatOfficialAccountAdapter,
    WechatProtocolError,
)
from model.account import Account, AccountStatus
from model.platform import (
    EnterpriseStatus,
    EnterpriseExternalAccount,
    IntegrationConnection,
    IntegrationConnectionStatus,
    PlatformAuditEvent,
    PlatformAuthSession,
    PlatformChannelCredential,
    PlatformChannelCredentialStatus,
    PlatformChannelIdentity,
    PlatformChannelIdentityStatus,
    PlatformConversation,
    PlatformCredential,
    PlatformDeliveryTask,
    PlatformEvidence,
    PlatformExecutionRun,
    PlatformEnterprise,
    PlatformMembership,
    PlatformMessage,
    PlatformMigration,
    PlatformRole,
    PlatformStatus,
    PlatformToolDefinition,
    PlatformUser,
)
from util.auth_cookie import add_auth_token_cookie
from util.helper import get_remote_ip
from util.password import hash as password_hash


app: TAgenticApp = TAgenticApp.get_app()
logger = logging.getLogger(__name__)


def _trace_id(request: Request) -> str:
    value = request.headers.get("X-Request-Id") or request.headers.get("X-Trace-Id")
    return value[:64] if value else uuid.uuid4().hex


def _body(request: Request) -> dict[str, Any]:
    body = request.json
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise PlatformBadRequest("请求体必须是 JSON 对象")
    return body


def _token_from_request(request: Request) -> str | None:
    authorization = request.headers.get("Authorization", "").strip()
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
        # Do not accept arbitrary legacy Authorization formats on platform APIs.
        raise AccountUnauthorized("平台登录态无效")
    return request.cookies.get("token")


def _require_adp_service(request: Request) -> None:
    """Only the server-side ADP adapter may reach internal execution routes."""
    provided = request.headers.get("X-ADP-Service-Token")
    if not is_adp_service_token_valid(provided, tagentic_config.ADP_TOOL_SERVICE_TOKEN):
        raise AccountUnauthorized("内部服务身份无效")


def _require_channel_service(request: Request) -> None:
    """Only a trusted channel adapter may assert the original sender identity."""
    provided = request.headers.get("X-Channel-Service-Token")
    if not is_adp_service_token_valid(provided, tagentic_config.PLATFORM_CHANNEL_SERVICE_TOKEN):
        raise AccountUnauthorized("渠道服务身份无效")


def _execution_token_from_request(request: Request) -> str:
    token = request.headers.get("X-Platform-Context-Token", "").strip()
    if not token:
        raise AccountUnauthorized("需要执行上下文")
    return token


def _tool_request_id(request: Request) -> str:
    value = request.headers.get("X-ADP-Request-Id", "").strip()
    if not value:
        raise PlatformBadRequest("缺少工具请求 ID")
    return value


def platform_required(view):
    @wraps(view)
    async def decorated(*args, **kwargs):
        request = next((item for item in args if hasattr(item, "ctx") and hasattr(item, "headers")), None)
        if request is None:
            request = kwargs.get("request")
        if request is None:
            raise AccountUnauthorized("平台登录态无效")
        token = _token_from_request(request)
        if not token:
            raise AccountUnauthorized("需要平台登录")
        context = await load_platform_context(request.ctx.db, token)
        request.ctx.platform = context
        return await view(*args, **kwargs)

    return decorated


def _context(request: Request) -> PlatformContext:
    context = getattr(request.ctx, "platform", None)
    if context is None:
        raise AccountUnauthorized("需要平台登录")
    return context


async def _commit_audit(
    request: Request,
    *,
    action: str,
    target_type: str,
    target_id: str | None = None,
    outcome: str = "success",
    metadata: dict[str, Any] | None = None,
    actor_account_id: str | None = None,
) -> None:
    context = getattr(request.ctx, "platform", None)
    await create_audit(
        request.ctx.db,
        actor_account_id=actor_account_id if actor_account_id is not None else (str(context.account.Id) if context else None),
        action=action,
        target_type=target_type,
        target_id=target_id,
        trace_id=_trace_id(request),
        outcome=outcome,
        metadata=metadata,
    )
    await request.ctx.db.commit()


def _serialize_evidence(item: PlatformEvidence) -> dict[str, Any]:
    return {
        "label": item.Label,
        "value": item.Value,
        "source": item.Source,
        "capturedAt": item.CapturedAt.isoformat() if item.CapturedAt else "",
        "known": bool(item.Known),
    }


def _serialize_session(
    session: PlatformConversation,
    run: PlatformExecutionRun | None = None,
    *,
    evidence_count: int = 0,
) -> dict[str, Any]:
    title = session.Title or "业务查询"
    query = run.Query if run is not None else (title.split(" / ", 1)[1] if " / " in title else "")
    return {
        "id": str(session.Id),
        "title": run.Title if run is not None and run.Title else title,
        "query": query,
        "channel": session.Channel,
        "preview": run.Summary if run is not None else "平台会话尚未产生业务查询结果。",
        "updatedAt": (run.CompletedAt or run.StartedAt).isoformat() if run is not None else (session.LastActiveAt.isoformat() if session.LastActiveAt else ""),
        "evidence": evidence_count > 0,
    }


def _serialize_run_result(run: PlatformExecutionRun, evidence: list[PlatformEvidence]) -> dict[str, Any]:
    return {
        "status": run.Status,
        "query": run.Query,
        "title": run.Title,
        "summary": run.Summary,
        "evidence": [_serialize_evidence(item) for item in evidence],
        "traceId": run.TraceId,
        "conversationId": str(run.ConversationId),
    }


async def _latest_runs(
    db,
    *,
    account_id: Any,
    conversation_ids: list[str],
) -> dict[str, PlatformExecutionRun]:
    if not conversation_ids:
        return {}
    rows = list((await db.execute(
        select(PlatformExecutionRun)
        .where(
            PlatformExecutionRun.AccountId == account_id,
            PlatformExecutionRun.ConversationId.in_(conversation_ids),
        )
        .order_by(PlatformExecutionRun.StartedAt.desc())
    )).scalars().all())
    return {str(row.ConversationId): row for row in reversed(rows)}


def _validated_conversation_id(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise PlatformBadRequest("会话 ID 格式不正确")
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise PlatformBadRequest("会话 ID 格式不正确") from exc


def _grouped_status_counts(rows: list[tuple[Any, Any]]) -> dict[str, int]:
    """Serialize grouped status queries without exposing row payloads."""
    return {str(status): int(count or 0) for status, count in rows}


def _error_category(value: Any) -> str:
    """Map provider/task errors to a small, non-sensitive diagnostic vocabulary."""
    normalized = str(value or "").lower()
    if "authorization_revoked" in normalized or "permission" in normalized or "unauthor" in normalized:
        return "authorization"
    if "timeout" in normalized or "timed out" in normalized:
        return "timeout"
    if "connection" in normalized or "connect" in normalized or "network" in normalized:
        return "network"
    if "upstream" in normalized or "provider" in normalized or "m3" in normalized or "adp" in normalized:
        return "upstream"
    if "schema" in normalized or "migration" in normalized or "database" in normalized:
        return "database"
    if normalized:
        return "other"
    return "unknown"


def _metadata_status_summary() -> dict[str, Any]:
    """Return counts only; application IDs and provider errors stay private."""
    from middleware.application import CoreApplication

    statuses = list((CoreApplication.metadata_status or {}).values())
    degraded = sum(1 for status in statuses if status.get("status") == "degraded")
    healthy = sum(1 for status in statuses if status.get("status") == "healthy")
    last_failure = max(
        (status.get("lastFailureAt") for status in statuses if status.get("lastFailureAt")),
        default=None,
    )
    return {
        "status": "degraded" if degraded else "healthy",
        "configuredApplications": len(statuses),
        "healthyApplications": healthy,
        "degradedApplications": degraded,
        "lastFailureAt": last_failure,
    }


def _ops_suggestions(
    *,
    schema_revision: int | None,
    delivery_counts: dict[str, int],
    run_counts: dict[str, int],
    metadata: dict[str, Any],
    expected_revision: int,
) -> list[dict[str, str]]:
    suggestions: list[dict[str, str]] = []
    if schema_revision != expected_revision:
        suggestions.append({
            "code": "schema_not_ready",
            "message": "数据库版本未达到当前发布版本；先执行迁移并再次检查就绪状态。",
        })
    if metadata.get("status") == "degraded":
        suggestions.append({
            "code": "adp_metadata_degraded",
            "message": "ADP 应用元信息存在降级；检查脱敏审计分类，聊天能力按当前状态单独判断。",
        })
    if delivery_counts.get("uncertain", 0):
        suggestions.append({
            "code": "delivery_uncertain",
            "message": "存在结果未知的出站任务；先用上游状态查询或幂等键核对，不要直接重发。",
        })
    if delivery_counts.get("failed", 0):
        suggestions.append({
            "code": "delivery_failed",
            "message": "存在失败出站任务；按错误分类和 trace ID 排查，确认授权状态后再由用户发起新请求。",
        })
    if delivery_counts.get("queued", 0) or delivery_counts.get("processing", 0) or delivery_counts.get("running", 0):
        suggestions.append({
            "code": "delivery_backlog",
            "message": "仍有未完成任务；检查 Worker 租约、会话 FIFO 和上游延迟，不要修改任务幂等键。",
        })
    if run_counts.get("upstream_error", 0) or run_counts.get("failed", 0):
        suggestions.append({
            "code": "execution_errors",
            "message": "存在执行失败或上游错误；按 trace ID 区分 M3、ADP 和授权问题，不要把未知字段补成确定值。",
        })
    if not suggestions:
        suggestions.append({
            "code": "all_clear",
            "message": "当前只读检查未发现需要立即处理的异常。",
        })
    return suggestions


async def _load_ops_status(request: Request) -> tuple[dict[str, Any], int]:
    """Build a redacted operational snapshot from aggregate queries only."""
    from core.migration import Migration

    try:
        db = request.ctx.db
        current_revision = (
            await db.execute(
                select(func.max(PlatformMigration.Version)).where(
                    PlatformMigration.Status == "applied",
                    PlatformMigration.RolledBackAt.is_(None),
                )
            )
        ).scalar_one_or_none()
        delivery_rows = list(
            (
                await db.execute(
                    select(PlatformDeliveryTask.Status, func.count())
                    .group_by(PlatformDeliveryTask.Status)
                )
            ).all()
        )
        run_rows = list(
            (
                await db.execute(
                    select(PlatformExecutionRun.Status, func.count())
                    .group_by(PlatformExecutionRun.Status)
                )
            ).all()
        )
        failure_rows = list(
            (
                await db.execute(
                    select(
                        PlatformAuditEvent.Action,
                        PlatformAuditEvent.Outcome,
                        func.count(),
                        func.max(PlatformAuditEvent.CreatedAt),
                    )
                    .where(PlatformAuditEvent.Outcome.notin_(("success", "found")))
                    .group_by(PlatformAuditEvent.Action, PlatformAuditEvent.Outcome)
                    .order_by(func.max(PlatformAuditEvent.CreatedAt).desc())
                    .limit(8)
                )
            ).all()
        )
    except Exception as error:  # diagnostics must never expose SQL or credentials
        logger.warning("[ops.status] aggregate query failed errorType=%s", type(error).__name__)
        return {
            "status": "degraded",
            "service": {"status": "ok"},
            "database": {"status": "error", "reason": type(error).__name__},
            "schema": {
                "currentRevision": None,
                "expectedRevision": Migration.CURRENT_PLATFORM_SCHEMA_VERSION,
            },
            "metadata": {"status": "unknown"},
            "delivery": {"byStatus": {}},
            "executions": {"byStatus": {}},
            "recentFailures": [],
            "suggestions": [{
                "code": "ops_query_failed",
                "message": "状态聚合查询失败；检查数据库就绪状态和服务日志中的错误分类。",
            }],
        }, 503

    delivery_counts = _grouped_status_counts(delivery_rows)
    run_counts = _grouped_status_counts(run_rows)
    metadata = _metadata_status_summary()
    failures = [
        {
            "action": str(action),
            "outcome": _error_category(outcome),
            "count": int(count or 0),
            "lastSeenAt": last_seen.isoformat() if last_seen else None,
        }
        for action, outcome, count, last_seen in failure_rows
    ]
    revision = int(current_revision) if current_revision is not None else None
    suggestions = _ops_suggestions(
        schema_revision=revision,
        delivery_counts=delivery_counts,
        run_counts=run_counts,
        metadata=metadata,
        expected_revision=Migration.CURRENT_PLATFORM_SCHEMA_VERSION,
    )
    has_degraded_state = (
        revision != Migration.CURRENT_PLATFORM_SCHEMA_VERSION
        or metadata.get("status") == "degraded"
        or bool(delivery_counts.get("uncertain") or delivery_counts.get("failed"))
        or bool(run_counts.get("upstream_error") or run_counts.get("failed"))
    )
    return {
        "status": "degraded" if has_degraded_state else "ok",
        "service": {"status": "ok"},
        "database": {"status": "ready"},
        "schema": {
            "currentRevision": revision,
            "expectedRevision": Migration.CURRENT_PLATFORM_SCHEMA_VERSION,
        },
        "metadata": metadata,
        "delivery": {"byStatus": delivery_counts},
        "executions": {"byStatus": run_counts},
        "recentFailures": failures,
        "suggestions": suggestions,
    }, 200


class OpsStatusApi(HTTPMethodView):
    """Read-only, aggregate operational status for the ops role."""

    @platform_required
    async def get(self, request: Request):
        require_permission(_context(request), "platform.diagnose")
        payload, status = await _load_ops_status(request)
        return json(payload, status=status)


async def _get_or_create_lookup_conversation(
    request: Request,
    *,
    context: PlatformContext,
    enterprise: PlatformEnterprise,
    query: str,
    conversation_id: Any,
) -> PlatformConversation:
    validated_id = _validated_conversation_id(conversation_id)
    conversation = None
    if validated_id is not None:
        conversation = (
            await request.ctx.db.execute(
                select(PlatformConversation).where(
                    PlatformConversation.Id == validated_id,
                    PlatformConversation.AccountId == context.account.Id,
                    PlatformConversation.EnterpriseId == enterprise.Id,
                )
            )
        ).scalar_one_or_none()
        if conversation is None:
            # Do not disclose whether a conversation belongs to another account
            # or enterprise.
            raise PlatformNotFound("会话不存在或无权访问")
    else:
        conversation = PlatformConversation(
            AccountId=context.account.Id,
            EnterpriseId=enterprise.Id,
            Channel="web",
            Title=f"业务查询 / {query.strip().upper()}"[:255],
        )
        request.ctx.db.add(conversation)
        await request.ctx.db.flush()

    conversation.LastActiveAt = utc_now()
    request.ctx.db.add(conversation)
    return conversation


class PlatformLoginApi(HTTPMethodView):
    async def post(self, request: Request):
        body = _body(request)
        phone = body.get("phone")
        password = body.get("password")
        try:
            token, context = await authenticate_platform(
                request.ctx.db,
                phone=phone,
                password=password,
                ip_address=get_remote_ip(request),
            )
        except (AccountAuthenticationError, PlatformBadRequest, RateLimit) as exc:
            await _commit_audit(
                request,
                action="auth.login",
                target_type="platform_user",
                outcome="failure",
                metadata={
                    "phone": "provided" if isinstance(phone, str) else "missing",
                    "rateLimited": isinstance(exc, RateLimit),
                },
                actor_account_id=None,
            )
            raise

        request.ctx.platform = context
        enterprise = await get_enterprise_for_user(request.ctx.db, context.user)
        await _commit_audit(
            request,
            action="auth.login",
            target_type="platform_user",
            target_id=str(context.user.Id),
            metadata={"role": context.user.Role},
        )
        response = json({
            "token": token,
            "user": serialize_user(context.user),
            "enterprise": serialize_enterprise(enterprise, context.permissions) if enterprise else None,
            "permissions": sorted(context.permissions),
            "mustReset": bool((await request.ctx.db.execute(
                select(PlatformCredential.MustReset).where(PlatformCredential.AccountId == context.account.Id)
            )).scalar_one_or_none()),
        })
        add_auth_token_cookie(
            response,
            config=app.config,
            token=token,
            max_age=tagentic_config.ACCESS_TOKEN_EXPIRE_HOURS * 3600,
            path="/",
        )
        return response


class PlatformLogoutApi(HTTPMethodView):
    @platform_required
    async def post(self, request: Request):
        context = _context(request)
        context.session.RevokedAt = utc_now()
        request.ctx.db.add(context.session)
        await revoke_account_execution_contexts(request.ctx.db, str(context.account.Id))
        await _commit_audit(request, action="auth.logout", target_type="platform_session", target_id=str(context.session.Id))
        response = json({"success": True})
        response.delete_cookie("token", path="/")
        return response


class PlatformSessionApi(HTTPMethodView):
    """Return the current platform identity so a browser refresh is recoverable."""

    @platform_required
    async def get(self, request: Request):
        context = _context(request)
        enterprise = await get_enterprise_for_user(request.ctx.db, context.user)
        must_reset = bool((await request.ctx.db.execute(
            select(PlatformCredential.MustReset).where(PlatformCredential.AccountId == context.account.Id)
        )).scalar_one_or_none())
        return json({
            "token": "",
            "user": serialize_user(context.user),
            "enterprise": serialize_enterprise(enterprise, context.permissions) if enterprise else None,
            "permissions": sorted(context.permissions),
            "mustReset": must_reset,
        })


class PortalOverviewApi(HTTPMethodView):
    @platform_required
    async def get(self, request: Request):
        context = _context(request)
        enterprise = await get_enterprise_for_user(request.ctx.db, context.user)
        sessions = list((await request.ctx.db.execute(
            select(PlatformConversation).where(PlatformConversation.AccountId == context.account.Id).order_by(PlatformConversation.LastActiveAt.desc()).limit(20)
        )).scalars().all())
        latest_runs = await _latest_runs(
            request.ctx.db,
            account_id=context.account.Id,
            conversation_ids=[str(item.Id) for item in sessions],
        )
        evidence_counts = {}
        if latest_runs:
            evidence_rows = list((await request.ctx.db.execute(
                select(PlatformEvidence.ExecutionRunId, func.count())
                .where(PlatformEvidence.ExecutionRunId.in_([item.Id for item in latest_runs.values()]))
                .group_by(PlatformEvidence.ExecutionRunId)
            )).all())
            evidence_counts = {str(run_id): int(count) for run_id, count in evidence_rows}
        total = (await request.ctx.db.execute(
            select(func.count()).select_from(PlatformConversation).where(PlatformConversation.AccountId == context.account.Id)
        )).scalar_one()
        services = [
            {"name": "M3 业务数据", "detail": "只读查询网关", "status": "healthy" if (tagentic_config.M3_USE_MOCK or tagentic_config.M3_BASE_URL) else "offline", "updatedAt": "实时"},
            {"name": "AI 助手", "detail": "回答与证据整理", "status": "healthy", "updatedAt": "运行正常"},
            {"name": "消息投递", "detail": "官网会话", "status": "healthy", "updatedAt": "运行正常"},
        ]
        return json({
            "user": serialize_user(context.user),
            "enterprise": serialize_enterprise(enterprise, context.permissions) if enterprise else None,
            "stats": {"activeShipments": 0, "pendingMilestones": 0, "recentQueries": int(total or 0)},
            "services": services,
            "sessions": [
                _serialize_session(
                    item,
                    latest_runs.get(str(item.Id)),
                    evidence_count=evidence_counts.get(str(latest_runs.get(str(item.Id)).Id), 0) if latest_runs.get(str(item.Id)) else 0,
                )
                for item in sessions
            ],
            "permissions": sorted(context.permissions),
        })


class PortalSessionsApi(HTTPMethodView):
    @platform_required
    async def get(self, request: Request):
        context = _context(request)
        sessions = list((await request.ctx.db.execute(
            select(PlatformConversation).where(PlatformConversation.AccountId == context.account.Id).order_by(PlatformConversation.LastActiveAt.desc()).limit(100)
        )).scalars().all())
        latest_runs = await _latest_runs(
            request.ctx.db,
            account_id=context.account.Id,
            conversation_ids=[str(item.Id) for item in sessions],
        )
        evidence_counts = {}
        if latest_runs:
            evidence_rows = list((await request.ctx.db.execute(
                select(PlatformEvidence.ExecutionRunId, func.count())
                .where(PlatformEvidence.ExecutionRunId.in_([item.Id for item in latest_runs.values()]))
                .group_by(PlatformEvidence.ExecutionRunId)
            )).all())
            evidence_counts = {str(run_id): int(count) for run_id, count in evidence_rows}
        return json([
            _serialize_session(
                item,
                latest_runs.get(str(item.Id)),
                evidence_count=evidence_counts.get(str(latest_runs.get(str(item.Id)).Id), 0) if latest_runs.get(str(item.Id)) else 0,
            )
            for item in sessions
        ])


class PortalSessionDetailApi(HTTPMethodView):
    @platform_required
    async def get(self, request: Request, conversation_id: str):
        context = _context(request)
        validated_id = _validated_conversation_id(conversation_id)
        conversation = (await request.ctx.db.execute(
            select(PlatformConversation).where(
                PlatformConversation.Id == validated_id,
                PlatformConversation.AccountId == context.account.Id,
            )
        )).scalar_one_or_none()
        if conversation is None:
            raise PlatformNotFound("会话不存在或无权访问")

        runs = list((await request.ctx.db.execute(
            select(PlatformExecutionRun)
            .where(
                PlatformExecutionRun.ConversationId == conversation.Id,
                PlatformExecutionRun.AccountId == context.account.Id,
                PlatformExecutionRun.EnterpriseId == conversation.EnterpriseId,
            )
            .order_by(PlatformExecutionRun.StartedAt.asc())
        )).scalars().all())
        run_ids = [item.Id for item in runs]
        evidence_rows = list((await request.ctx.db.execute(
            select(PlatformEvidence)
            .where(
                PlatformEvidence.ConversationId == conversation.Id,
                PlatformEvidence.AccountId == context.account.Id,
                PlatformEvidence.ExecutionRunId.in_(run_ids) if run_ids else False,
            )
            .order_by(PlatformEvidence.CapturedAt.asc())
        )).scalars().all()) if run_ids else []
        evidence_by_run: dict[str, list[PlatformEvidence]] = {}
        for item in evidence_rows:
            evidence_by_run.setdefault(str(item.ExecutionRunId), []).append(item)
        messages = list((await request.ctx.db.execute(
            select(PlatformMessage)
            .where(
                PlatformMessage.ConversationId == conversation.Id,
                PlatformMessage.AccountId == context.account.Id,
                PlatformMessage.EnterpriseId == conversation.EnterpriseId,
            )
            .order_by(PlatformMessage.CreatedAt.asc())
        )).scalars().all())
        latest = runs[-1] if runs else None
        return json({
            "conversation": _serialize_session(
                conversation,
                latest,
                evidence_count=len(evidence_by_run.get(str(latest.Id), [])) if latest else 0,
            ),
            "messages": [{
                "id": str(item.Id),
                "direction": item.Direction,
                "messageType": item.MessageType,
                "body": item.Body or "",
                "runId": str(item.ExecutionRunId) if item.ExecutionRunId else None,
                "traceId": item.TraceId,
                "createdAt": item.CreatedAt.isoformat() if item.CreatedAt else "",
            } for item in messages],
            "runs": [{
                "runId": item.RunId,
                "status": item.Status,
                "query": item.Query,
                "title": item.Title,
                "summary": item.Summary,
                "traceId": item.TraceId,
                "startedAt": item.StartedAt.isoformat() if item.StartedAt else "",
                "completedAt": item.CompletedAt.isoformat() if item.CompletedAt else None,
                "evidence": [_serialize_evidence(evidence) for evidence in evidence_by_run.get(str(item.Id), [])],
            } for item in runs],
            "result": _serialize_run_result(latest, evidence_by_run.get(str(latest.Id), [])) if latest else None,
        })


def _m3_adapter() -> M3LookupAdapter:
    return M3LookupAdapter(
        use_mock=bool(tagentic_config.M3_USE_MOCK),
        base_url=tagentic_config.M3_BASE_URL,
        timeout_seconds=tagentic_config.M3_TIMEOUT_SECONDS,
    )


class ShipmentLookupApi(HTTPMethodView):
    @platform_required
    async def post(self, request: Request):
        context = _context(request)
        require_permission(context, "shipment.read")
        enterprise = await get_enterprise_for_user(request.ctx.db, context.user)
        if enterprise is None:
            raise PlatformForbidden("当前账号没有可访问的企业范围")
        body = _body(request)
        query = body.get("query")
        if not isinstance(query, str) or not query.strip():
            raise PlatformBadRequest("请输入提单号或箱号")
        conversation = await _get_or_create_lookup_conversation(
            request,
            context=context,
            enterprise=enterprise,
            query=query,
            conversation_id=body.get("conversationId"),
        )
        request_trace_id = _trace_id(request)
        run = PlatformExecutionRun(
            ConversationId=conversation.Id,
            AccountId=context.account.Id,
            EnterpriseId=enterprise.Id,
            RunId=f"run_{uuid.uuid4().hex[:32]}",
            Query=query.strip().upper()[:128],
            Status="running",
            Title="业务查询",
            Summary="",
            TraceId=request_trace_id,
        )
        request.ctx.db.add(run)
        await request.ctx.db.flush()
        request.ctx.db.add(PlatformMessage(
            ConversationId=conversation.Id,
            AccountId=context.account.Id,
            EnterpriseId=enterprise.Id,
            ExecutionRunId=run.Id,
            Direction="inbound",
            MessageType="text",
            Body=query.strip(),
            Payload={},
            TraceId=request_trace_id,
        ))
        result = await _m3_adapter().lookup(query=query, customer_code=enterprise.CustomerCode)
        run.Status = result.status
        run.Title = result.title[:255]
        run.Summary = result.summary
        run.TraceId = result.trace_id
        run.CompletedAt = utc_now()
        request.ctx.db.add(run)
        for evidence in result.evidence:
            request.ctx.db.add(PlatformEvidence(
                ExecutionRunId=run.Id,
                ConversationId=conversation.Id,
                AccountId=context.account.Id,
                EnterpriseId=enterprise.Id,
                Label=str(evidence.get("label", ""))[:128],
                Value=str(evidence.get("value", "")),
                Source=str(evidence.get("source", ""))[:255],
                CapturedAt=utc_now(),
                Known=bool(evidence.get("known", False)),
            ))
        request.ctx.db.add(PlatformMessage(
            ConversationId=conversation.Id,
            AccountId=context.account.Id,
            EnterpriseId=enterprise.Id,
            ExecutionRunId=run.Id,
            Direction="assistant",
            MessageType="shipment.result",
            Body=result.summary,
            Payload={"status": result.status, "title": result.title, "query": result.query},
            TraceId=result.trace_id,
        ))
        conversation.LastActiveAt = utc_now()
        conversation.Title = f"业务查询 / {result.query}"[:255]
        request.ctx.db.add(conversation)
        await _commit_audit(
            request,
            action="shipment.lookup",
            target_type="platform_conversation",
            target_id=str(conversation.Id),
            outcome=result.audit_outcome or result.status,
            metadata={"status": result.status, "enterpriseId": str(enterprise.Id), "runId": run.RunId, "evidenceCount": len(result.evidence)},
        )
        payload = result.to_dict()
        payload["conversationId"] = str(conversation.Id)
        return json(payload)


class WebChannelInboundApi(HTTPMethodView):
    """Accept one authenticated website message and enqueue it exactly once."""

    @platform_required
    async def post(self, request: Request):
        context = _context(request)
        require_permission(context, "shipment.read")
        enterprise = await get_enterprise_for_user(request.ctx.db, context.user)
        if enterprise is None:
            raise PlatformForbidden("当前账号没有可访问的企业范围")

        body = _body(request)
        try:
            adapter = register_default_adapters().get("web", "web-portal")
        except ChannelRegistryError as exc:
            raise PlatformBadRequest("Web 渠道适配器未注册") from exc
        envelope = adapter.normalize(
            context=context,
            text=body.get("text"),
            conversation_id=body.get("conversationId"),
            message_id=body.get("messageId") or request.headers.get("X-Message-Id"),
            trace_id=_trace_id(request),
        )
        # The enterprise ID is deliberately assigned after normalization. It
        # comes from the authenticated membership, never from the browser.
        task_payload = dict(envelope.task_payload)
        task_payload["enterpriseId"] = str(enterprise.Id)
        inbound, task, created = await record_inbound_message(
            request.ctx.db,
            message=envelope.message,
            task_type=PLATFORM_INBOUND_TASK_TYPE,
            task_payload=task_payload,
            max_attempts=PLATFORM_INBOUND_MAX_ATTEMPTS,
        )
        await request.ctx.db.commit()
        return json(
            {
                "inboundMessageId": str(inbound.Id),
                "taskId": str(task.Id) if task is not None else None,
                "created": created,
                "status": inbound.Status,
                "channel": adapter.channel,
                "conversationId": envelope.conversation_id,
            },
            status=201 if created else 200,
        )


class WebChannelInboundStatusApi(HTTPMethodView):
    """Expose redacted progress for a portal Web message while it is processed."""

    @platform_required
    async def get(self, request: Request, inbound_id: str):
        context = _context(request)
        require_permission(context, "shipment.read")
        inbound_id = _required_uuid({"inboundId": inbound_id}, "inboundId")
        inbound = await request.ctx.db.get(PlatformInboundMessage, inbound_id)
        if inbound is None or inbound.ChannelInstanceId != "web-portal":
            raise PlatformNotFound("消息不存在或无权访问")
        if inbound.SenderIdentityId != str(context.user.Id):
            raise PlatformNotFound("消息不存在或无权访问")
        source_task = (await request.ctx.db.execute(select(PlatformDeliveryTask).where(
            PlatformDeliveryTask.TaskType == PLATFORM_INBOUND_TASK_TYPE,
            PlatformDeliveryTask.DeduplicationKey == f"web-portal:{inbound.ExternalMessageId}",
        ))).scalar_one_or_none()
        reply_task = (await request.ctx.db.execute(select(PlatformDeliveryTask).where(
            PlatformDeliveryTask.TaskType == "platform.reply",
            PlatformDeliveryTask.DeduplicationKey == f"platform-reply:{inbound_id}",
        ))).scalar_one_or_none()
        conversation_id = None
        if source_task is not None and isinstance(source_task.Payload, dict):
            conversation_id = source_task.Payload.get("conversationId")
        if conversation_id:
            try:
                conversation = (await request.ctx.db.execute(select(PlatformConversation).where(
                    PlatformConversation.Id == conversation_id,
                    PlatformConversation.AccountId == context.account.Id,
                ))).scalar_one_or_none()
            except Exception:
                conversation = None
            if conversation is None:
                conversation_id = None
        return json({
            "inboundMessageId": inbound_id,
            "inboundStatus": inbound.Status,
            "taskStatus": source_task.Status if source_task is not None else None,
            "replyStatus": reply_task.Status if reply_task is not None else None,
            "conversationId": conversation_id,
        })


def _wechat_credential(credential: Any) -> dict[str, str]:
    """Normalize legacy token-only and structured official-account credentials."""
    value = credential.strip() if isinstance(credential, str) else credential
    if isinstance(value, str) and value.startswith("{"):
        try:
            parsed = stdlib_json.loads(value)
        except (TypeError, ValueError) as exc:
            raise PlatformBadRequest("微信服务号凭据格式不正确") from exc
        if not isinstance(parsed, dict):
            raise PlatformBadRequest("微信服务号凭据格式不正确")
        result = {
            str(key): item.strip()
            for key, item in parsed.items()
            if key in {"token", "appId", "app_id", "appSecret", "app_secret", "encodingAesKey", "encoding_aes_key"}
            and isinstance(item, str)
            and item.strip()
        }
    elif isinstance(value, dict):
        parsed = value
        result = {
            str(key): item.strip()
            for key, item in parsed.items()
            if key in {"token", "appId", "app_id", "appSecret", "app_secret", "encodingAesKey", "encoding_aes_key"}
            and isinstance(item, str)
            and item.strip()
        }
    else:
        result = {"token": value}
    raw_token = result.get("token", "")
    token = raw_token.strip() if isinstance(raw_token, str) else ""
    if not token or len(token) > 512:
        raise PlatformBadRequest("微信服务号凭据格式不正确")
    result["token"] = token
    app_id = result.get("appId") or result.get("app_id")
    aes_key = result.get("encodingAesKey") or result.get("encoding_aes_key")
    if aes_key and not app_id:
        raise PlatformBadRequest("配置EncodingAESKey时必须同时提供AppID")
    if app_id and len(app_id) > 128:
        raise PlatformBadRequest("微信AppID格式不正确")
    if aes_key and len(aes_key) not in (43, 44):
        raise PlatformBadRequest("微信EncodingAESKey格式不正确")
    return result


async def _wechat_adapter(request: Request, channel_instance_id: str) -> WechatOfficialAccountAdapter:
    if not isinstance(channel_instance_id, str) or not channel_instance_id.strip() or len(channel_instance_id) > 128:
        raise PlatformBadRequest("渠道实例格式不正确")
    try:
        credential = await load_active_channel_instance_credential(
            request.ctx.db,
            channel=WECHAT_OFFICIAL_ACCOUNT,
            channel_instance_id=channel_instance_id.strip(),
        )
    except ChannelCredentialError as exc:
        raise PlatformForbidden("微信服务号渠道未配置") from exc
    config = _wechat_credential(credential)
    try:
        return WechatOfficialAccountAdapter(
            channel_instance_id=channel_instance_id.strip(),
            token=config["token"],
            app_id=config.get("appId") or config.get("app_id"),
            encoding_aes_key=config.get("encodingAesKey") or config.get("encoding_aes_key"),
        )
    except ValueError as exc:
        raise PlatformBadRequest("微信服务号安全模式凭据格式不正确") from exc


class WechatOfficialAccountCallbackApi(HTTPMethodView):
    """Public WeChat callback; only durable enqueue work happens here."""

    async def get(self, request: Request, channel_instance_id: str):
        adapter = await _wechat_adapter(request, channel_instance_id)
        try:
            echo = adapter.verification_echo(
                signature=request.args.get("signature", ""),
                timestamp=request.args.get("timestamp", ""),
                nonce=request.args.get("nonce", ""),
                echostr=request.args.get("echostr", ""),
                msg_signature=request.args.get("msg_signature"),
                encrypted=request.args.get("encrypt_type", "").lower() == "aes",
            )
        except WechatProtocolError:
            raise
        return text(echo)

    async def post(self, request: Request, channel_instance_id: str):
        adapter = await _wechat_adapter(request, channel_instance_id)
        encrypted = request.args.get("encrypt_type", "").lower() == "aes" or bool(request.args.get("msg_signature"))
        if encrypted:
            encrypted_body = adapter.extract_encrypted(request.body)
            adapter.verify_encrypted_callback(
                msg_signature=request.args.get("msg_signature", ""),
                timestamp=request.args.get("timestamp", ""),
                nonce=request.args.get("nonce", ""),
                encrypt=encrypted_body,
            )
            body = adapter.decrypt_xml(encrypted_body)
        else:
            adapter.verify_callback(
                signature=request.args.get("signature", ""),
                timestamp=request.args.get("timestamp", ""),
                nonce=request.args.get("nonce", ""),
            )
            body = request.body
        envelope = adapter.normalize_xml(body=body, trace_id=_trace_id(request))
        identity = await resolve_active_channel_identity(
            request.ctx.db,
            channel=adapter.channel,
            channel_instance_id=adapter.channel_instance_id,
            external_identity_id=envelope.open_id,
        )
        if identity is None:
            raise PlatformForbidden("微信身份尚未绑定平台账号")
        task_payload = dict(envelope.task_payload)
        task_payload.update({
            "platformUserId": str(identity.UserId),
            "enterpriseId": str(identity.EnterpriseId),
            "accountId": str(identity.AccountId),
            "channel": adapter.channel,
            "traceId": envelope.message.trace_id,
        })
        inbound, task, created = await record_inbound_message(
            request.ctx.db,
            message=envelope.message,
            task_type=PLATFORM_INBOUND_TASK_TYPE,
            task_payload=task_payload,
            max_attempts=PLATFORM_INBOUND_MAX_ATTEMPTS,
        )
        await request.ctx.db.commit()
        # WeChat accepts the literal success body.  Detailed task IDs stay out
        # of the provider response and are available through platform storage.
        return text("success", status=200)


async def _default_wechat_instance_id(request: Request) -> str:
    """Resolve the fixed callback only when exactly one instance is active.

    WeChat Official Account callbacks do not include the AppID in the XML
    payload (``ToUserName`` is the public account identifier), so guessing
    between multiple tokens would be unsafe. Deployments with multiple
    accounts must use the instance-specific URL.
    """
    try:
        rows = await load_active_channel_credentials(request.ctx.db, channel=WECHAT_OFFICIAL_ACCOUNT)
    except ChannelCredentialError as exc:
        raise PlatformForbidden("微信服务号渠道未配置") from exc
    if len(rows) != 1:
        raise PlatformForbidden("固定微信回调要求且仅允许一个启用的服务号实例")
    return rows[0][0]


class WechatOfficialAccountFixedCallbackApi(WechatOfficialAccountCallbackApi):
    async def get(self, request: Request):
        return await super().get(request, await _default_wechat_instance_id(request))

    async def post(self, request: Request):
        return await super().post(request, await _default_wechat_instance_id(request))


class AdpExecutionContextApi(HTTPMethodView):
    """Mint a scoped token for the trusted server-side ADP adapter."""

    async def post(self, request: Request):
        _require_adp_service(request)
        body = _body(request)
        platform_token = body.get("platformToken")
        if not isinstance(platform_token, str) or not platform_token:
            raise AccountUnauthorized("需要平台会话")
        platform_context = await load_platform_context(request.ctx.db, platform_token)
        raw_token, execution = await issue_execution_context(
            request.ctx.db,
            platform_context=platform_context,
            agent_id=body.get("agentId", "platform-default"),
            channel=body.get("channel", "web"),
            enterprise_id=body.get("enterpriseId"),
            conversation_id=body.get("conversationId"),
            run_id=body.get("runId"),
            ttl_seconds=body.get("ttlSeconds", tagentic_config.ADP_EXECUTION_CONTEXT_TTL_SECONDS),
        )
        await create_audit(
            request.ctx.db,
            actor_account_id=str(platform_context.account.Id),
            action="adp.execution_context.issue",
            target_type="platform_execution_context",
            target_id=str(execution.Id),
            trace_id=_trace_id(request),
            metadata={
                "runId": execution.RunId,
                "agentId": execution.AgentId,
                "channel": execution.Channel,
                "enterpriseId": str(execution.EnterpriseId),
                "expiresAt": execution.ExpiresAt.isoformat(),
            },
        )
        await request.ctx.db.commit()
        return json({
            "contextToken": raw_token,
            "contextId": str(execution.Id),
            "runId": execution.RunId,
            "userId": str(execution.UserId),
            "enterpriseId": str(execution.EnterpriseId),
            "agentId": execution.AgentId,
            "channel": execution.Channel,
            "conversationId": str(execution.ConversationId) if execution.ConversationId else None,
            "expiresAt": execution.ExpiresAt.isoformat(),
        }, status=201)


class AdminAdpChatContextApi(HTTPMethodView):
    """Issue a temporary legacy context for the Admin ADP Chat debugger."""

    @platform_required
    async def post(self, request: Request):
        context = _context(request)
        require_permission(context, "platform.manage")
        token, expires_at = create_admin_adp_context_token(context)
        await _commit_audit(
            request,
            action="adp.admin_debug_context.issue",
            target_type="admin_adp_chat_context",
            metadata={"expiresAt": expires_at.isoformat()},
        )
        return json({"contextToken": token, "expiresAt": expires_at.isoformat()}, status=201)


class PlatformInboundApi(HTTPMethodView):
    """Record a normalized channel callback for the platform worker."""

    async def post(self, request: Request):
        _require_adp_service(request)
        body = _body(request)

        def required_text(key: str, limit: int) -> str:
            value = body.get(key)
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
                raise PlatformBadRequest(f"{key}格式不正确")
            return value.strip()

        channel_instance_id = required_text("channelInstanceId", 128)
        external_message_id = required_text("externalMessageId", 255)
        external_conversation_id = required_text("externalConversationId", 255)
        sender_identity_id = required_text("senderIdentityId", 255)
        platform_user_id = required_text("platformUserId", 64)
        text = body.get("text")
        if text is not None and (not isinstance(text, str) or len(text) > 10000):
            raise PlatformBadRequest("消息文本格式不正确")
        message_type = body.get("messageType", "text")
        if not isinstance(message_type, str) or not message_type.strip() or len(message_type.strip()) > 32:
            raise PlatformBadRequest("消息类型格式不正确")
        trace_id = body.get("traceId") or _trace_id(request)
        if not isinstance(trace_id, str) or not trace_id.strip() or len(trace_id.strip()) > 64:
            raise PlatformBadRequest("Trace ID格式不正确")

        task_payload = {
            "platformUserId": platform_user_id,
            "platformSessionId": body.get("platformSessionId"),
            "enterpriseId": body.get("enterpriseId"),
            "conversationId": body.get("conversationId"),
            "channel": body.get("channel", "web"),
            "traceId": trace_id.strip(),
            "agentId": body.get("agentId", "platform-default"),
            "runId": body.get("runId"),
        }
        inbound, task, created = await record_inbound_message(
            request.ctx.db,
            message=InboundMessageInput(
                channel_instance_id=channel_instance_id,
                external_message_id=external_message_id,
                external_conversation_id=external_conversation_id,
                sender_identity_id=sender_identity_id,
                text=text,
                trace_id=trace_id.strip(),
                message_type=message_type.strip(),
                payload=body.get("payload"),
            ),
            task_type=PLATFORM_INBOUND_TASK_TYPE,
            task_payload=task_payload,
            max_attempts=PLATFORM_INBOUND_MAX_ATTEMPTS,
        )
        await request.ctx.db.commit()
        return json(
            {
                "inboundMessageId": str(inbound.Id),
                "taskId": str(task.Id) if task is not None else None,
                "created": created,
                "status": inbound.Status,
            },
            status=201 if created else 200,
        )


class AdpShipmentLookupApi(HTTPMethodView):
    """Internal ADP tool callback; browser sessions are never accepted here."""

    async def post(self, request: Request):
        _require_adp_service(request)
        request_id = _tool_request_id(request)
        execution = await load_execution_context(
            request.ctx.db,
            token=_execution_token_from_request(request),
            tool_name="shipment.lookup",
            request_id=request_id,
        )
        body = _body(request)
        query = body.get("query")
        if not isinstance(query, str) or not query.strip():
            raise PlatformBadRequest("请输入提单号或箱号")
        supplied_conversation = body.get("conversationId")
        if supplied_conversation not in (None, "") and str(supplied_conversation) != str(execution.context.ConversationId):
            raise PlatformForbidden("会话不属于当前执行上下文")

        trace_id = _trace_id(request)
        call = await claim_tool_call(
            request.ctx.db,
            execution=execution,
            tool_name="shipment.lookup",
            request_id=request_id,
            trace_id=trace_id,
            query=query,
        )
        try:
            result = await _m3_adapter().lookup(query=query, customer_code=execution.enterprise.CustomerCode)
        except Exception:  # Keep provider details out of the internal contract and logs.
            result = M3LookupResult(
                status="upstream_error",
                query=query.strip().upper(),
                title="M3 暂时无法响应",
                summary="业务系统暂时不可用，请稍后重试。平台没有使用未核实的数据替代结果。",
                audit_outcome="upstream_error",
            )
        await complete_tool_call(
            request.ctx.db,
            call=call,
            status="completed",
            outcome=result.audit_outcome or result.status,
            evidence=result.evidence,
        )
        await create_audit(
            request.ctx.db,
            actor_account_id=str(execution.account.Id),
            action="adp.tool_call",
            target_type="platform_tool_call",
            target_id=str(call.Id),
            trace_id=trace_id,
            outcome=result.audit_outcome or result.status,
            metadata={
                "tool": "shipment.lookup",
                "runId": execution.context.RunId,
                "contextId": str(execution.context.Id),
                "enterpriseId": str(execution.enterprise.Id),
                "evidenceCount": len(result.evidence),
            },
        )
        await request.ctx.db.commit()
        payload = result.to_dict()
        if execution.context.ConversationId:
            payload["conversationId"] = str(execution.context.ConversationId)
        return json(payload)


class ChannelIdentityBindApi(HTTPMethodView):
    """Start and inspect channel identities owned by the current user."""

    @platform_required
    async def get(self, request: Request):
        context = _context(request)
        rows = list(
            (
                await request.ctx.db.execute(
                    select(PlatformChannelIdentity)
                    .where(PlatformChannelIdentity.AccountId == context.account.Id)
                    .order_by(PlatformChannelIdentity.CreatedAt.desc())
                )
            ).scalars().all()
        )
        return json([serialize_channel_identity(row) for row in rows])

    @platform_required
    async def post(self, request: Request):
        context = _context(request)
        body = _body(request)
        enterprise_id = _required_uuid(body, "enterpriseId")
        channel = _required_channel_text(body, "channel", 48)
        channel_instance_id = _required_channel_text(body, "channelInstanceId", 128)
        external_identity_id = _required_channel_text(body, "externalIdentityId", 255)
        row, state = await begin_channel_identity_binding(
            request.ctx.db,
            user_id=str(context.user.Id),
            account_id=str(context.account.Id),
            enterprise_id=enterprise_id,
            channel=channel,
            channel_instance_id=channel_instance_id,
            external_identity_id=external_identity_id,
        )
        await _commit_audit(
            request,
            action="channel.identity.bind.start",
            target_type="platform_channel_identity",
            target_id=str(row.Id),
            metadata={
                "enterpriseId": str(row.EnterpriseId),
                "channel": row.Channel,
                "channelInstanceId": row.ChannelInstanceId,
                "externalIdentityFingerprint": external_identity_fingerprint(row.ExternalIdentityId),
            },
        )
        return json({"identity": serialize_channel_identity(row), "state": state})


class ChannelIdentityRevokeApi(HTTPMethodView):
    @platform_required
    async def post(self, request: Request, identity_id: str):
        context = _context(request)
        identity_id = _required_uuid({"identityId": identity_id}, "identityId")
        row = await revoke_channel_identity(
            request.ctx.db,
            identity_id=identity_id,
            account_id=str(context.account.Id),
        )
        await _commit_audit(
            request,
            action="channel.identity.revoke",
            target_type="platform_channel_identity",
            target_id=str(row.Id),
            metadata={
                "channel": row.Channel,
                "channelInstanceId": row.ChannelInstanceId,
                "externalIdentityFingerprint": external_identity_fingerprint(row.ExternalIdentityId),
            },
        )
        return json({"identity": serialize_channel_identity(row)})


class ChannelIdentityConfirmApi(HTTPMethodView):
    """Confirm a browser-started binding from the original channel sender."""

    async def post(self, request: Request):
        _require_channel_service(request)
        body = _body(request)
        state = _required_channel_text(body, "state", 256)
        channel = _required_channel_text(body, "channel", 48)
        channel_instance_id = _required_channel_text(body, "channelInstanceId", 128)
        external_identity_id = _required_channel_text(body, "externalIdentityId", 255)
        from core.channel_identity import channel_identity_state_hash

        pending = (
            await request.ctx.db.execute(
                select(PlatformChannelIdentity).where(
                    PlatformChannelIdentity.StateHash == channel_identity_state_hash(state),
                    PlatformChannelIdentity.Status == PlatformChannelIdentityStatus.PENDING,
                )
            )
        ).scalar_one_or_none()
        try:
            row = await confirm_channel_identity_binding(
                request.ctx.db,
                state=state,
                channel=channel,
                channel_instance_id=channel_instance_id,
                external_identity_id=external_identity_id,
            )
        except (PlatformBadRequest, PlatformForbidden, AccountUnauthorized) as exc:
            if pending is not None:
                await _commit_audit(
                    request,
                    action="channel.identity.confirm",
                    target_type="platform_channel_identity",
                    target_id=str(pending.Id),
                    outcome="rejected",
                    actor_account_id=str(pending.AccountId),
                    metadata={
                        "channel": channel,
                        "channelInstanceId": channel_instance_id,
                        "externalIdentityFingerprint": external_identity_fingerprint(external_identity_id),
                        "reason": exc.__class__.__name__,
                    },
                )
            raise
        await _commit_audit(
            request,
            action="channel.identity.confirm",
            target_type="platform_channel_identity",
            target_id=str(row.Id),
            actor_account_id=str(row.AccountId),
            metadata={
                "channel": row.Channel,
                "channelInstanceId": row.ChannelInstanceId,
                "externalIdentityFingerprint": external_identity_fingerprint(row.ExternalIdentityId),
            },
        )
        return json({"identity": serialize_channel_identity(row)})


class AdminOverviewApi(HTTPMethodView):
    @platform_required
    async def get(self, request: Request):
        context = _context(request)
        require_permission(context, "platform.manage")
        enterprises = (await request.ctx.db.execute(select(func.count()).select_from(PlatformEnterprise))).scalar_one()
        users = (await request.ctx.db.execute(select(func.count()).select_from(PlatformUser).where(PlatformUser.Status == PlatformStatus.ACTIVE))).scalar_one()
        read_only_tools = (await request.ctx.db.execute(
            select(func.count()).select_from(PlatformToolDefinition).where(
                PlatformToolDefinition.Enabled.is_(True),
                PlatformToolDefinition.ReadOnly.is_(True),
            )
        )).scalar_one()
        audit_failures = (await request.ctx.db.execute(select(func.count()).select_from(PlatformAuditEvent).where(PlatformAuditEvent.Outcome.notin_(("success", "found"))))).scalar_one()
        events = list((await request.ctx.db.execute(select(PlatformAuditEvent).order_by(PlatformAuditEvent.CreatedAt.desc()).limit(5))).scalars().all())
        config_state = await get_platform_config_state(request.ctx.db)
        published_config = config_state["published"] or {}
        published_payload = published_config.get("payload") or {}
        return json({
            "metrics": [
                {"label": "已接入企业", "value": str(enterprises or 0), "note": "平台企业目录", "tone": "neutral"},
                {"label": "活跃用户", "value": str(users or 0), "note": "可登录平台账号", "tone": "success"},
                {"label": "只读工具", "value": str(read_only_tools or 0), "note": "已启用且均需显式权限", "tone": "success"},
                {"label": "失败执行", "value": str(audit_failures or 0), "note": "审计事件统计", "tone": "warning"},
            ],
            "activities": [{
                "action": event.Action,
                "actor": str(event.ActorAccountId or "系统"),
                "target": event.TargetId or event.TargetType,
                "at": event.CreatedAt.isoformat() if event.CreatedAt else "",
                "tone": "success" if event.Outcome in {"success", "found"} else "warning",
            } for event in events],
            "config": {
                "version": f"v{published_config.get('version', 1)}",
                "status": published_config.get("status", "published"),
                "updatedAt": published_config.get("updatedAt") or published_config.get("createdAt") or "",
                "items": published_payload.get("items", []),
                "published": published_config,
                "draft": config_state.get("draft"),
                "history": config_state.get("history", []),
            },
        })


class AdminConfigApi(HTTPMethodView):
    @platform_required
    async def get(self, request: Request):
        require_permission(_context(request), "platform.manage")
        return json(await get_platform_config_state(request.ctx.db))


class AdminConfigDraftApi(HTTPMethodView):
    @platform_required
    async def post(self, request: Request):
        context = _context(request)
        require_permission(context, "platform.manage")
        body = _body(request)
        if "payload" not in body:
            raise PlatformBadRequest("缺少配置 payload")
        draft = await save_platform_config_draft(
            request.ctx.db,
            payload=body["payload"],
            actor_account_id=str(context.account.Id),
        )
        await _commit_audit(
            request,
            action="config.draft.save",
            target_type="platform_config",
            target_id=str(draft.Version),
            metadata={"version": int(draft.Version)},
        )
        return json(await get_platform_config_state(request.ctx.db))


class AdminConfigPublishApi(HTTPMethodView):
    @platform_required
    async def post(self, request: Request):
        context = _context(request)
        require_permission(context, "platform.manage")
        published = await publish_platform_config(
            request.ctx.db,
            actor_account_id=str(context.account.Id),
        )
        await _commit_audit(
            request,
            action="config.publish",
            target_type="platform_config",
            target_id=str(published.Version),
            metadata={"version": int(published.Version)},
        )
        return json(await get_platform_config_state(request.ctx.db))


class AdminConfigRollbackApi(HTTPMethodView):
    @platform_required
    async def post(self, request: Request):
        context = _context(request)
        require_permission(context, "platform.manage")
        body = _body(request)
        if "version" not in body:
            raise PlatformBadRequest("缺少回滚版本")
        target = await rollback_platform_config(
            request.ctx.db,
            version=body["version"],
            actor_account_id=str(context.account.Id),
        )
        await _commit_audit(
            request,
            action="config.rollback",
            target_type="platform_config",
            target_id=str(target.Version),
            metadata={"version": int(target.Version)},
        )
        return json(await get_platform_config_state(request.ctx.db))


class AdminEnterpriseListApi(HTTPMethodView):
    @platform_required
    async def get(self, request: Request):
        require_permission(_context(request), "platform.manage")
        rows = list((await request.ctx.db.execute(select(PlatformEnterprise).order_by(PlatformEnterprise.Name))).scalars().all())
        return json([{"id": str(row.Id), "name": row.Name, "customerCode": row.CustomerCode, "status": row.Status} for row in rows])

    @platform_required
    async def post(self, request: Request):
        context = _context(request)
        require_permission(context, "platform.manage")
        body = _body(request)
        enterprise = await create_enterprise(db=request.ctx.db, name=body.get("name"), customer_code=body.get("customerCode"))
        await _commit_audit(request, action="enterprise.create", target_type="enterprise", target_id=str(enterprise.Id), metadata={"customerCode": enterprise.CustomerCode})
        return json({"id": str(enterprise.Id), "name": enterprise.Name, "customerCode": enterprise.CustomerCode, "status": enterprise.Status}, status=201)


class AdminUserListApi(HTTPMethodView):
    @platform_required
    async def get(self, request: Request):
        require_permission(_context(request), "platform.manage")
        users = list((await request.ctx.db.execute(select(PlatformUser).order_by(PlatformUser.Name))).scalars().all())
        enterprises_by_user: dict[str, list[dict[str, Any]]] = {}
        if users:
            membership_rows = (
                await request.ctx.db.execute(
                    select(PlatformMembership, PlatformEnterprise)
                    .join(PlatformEnterprise, PlatformEnterprise.Id == PlatformMembership.EnterpriseId)
                    .where(
                        PlatformMembership.UserId.in_([user.Id for user in users]),
                        PlatformMembership.Active.is_(True),
                    )
                    .order_by(PlatformEnterprise.Name)
                )
            ).all()
            for membership, enterprise in membership_rows:
                enterprises_by_user.setdefault(str(membership.UserId), []).append({
                    "id": str(enterprise.Id),
                    "name": enterprise.Name,
                    "customerCode": enterprise.CustomerCode,
                    "status": enterprise.Status,
                })
        return json([{
            **serialize_user(user),
            "status": user.Status,
            "enterprises": enterprises_by_user.get(str(user.Id), []),
        } for user in users])

    @platform_required
    async def post(self, request: Request):
        context = _context(request)
        require_permission(context, "platform.manage")
        body = _body(request)
        user, initial_password = await create_platform_user(
            request.ctx.db,
            name=body.get("name"),
            phone=body.get("phone"),
            role=body.get("role", PlatformRole.CUSTOMER),
            enterprise_id=body.get("enterpriseId"),
        )
        await _commit_audit(request, action="user.create", target_type="platform_user", target_id=str(user.Id), metadata={"role": user.Role})
        return json({"user": {**serialize_user(user), "status": user.Status}, "initialPassword": initial_password}, status=201)


class AdminUserResetPasswordApi(HTTPMethodView):
    @platform_required
    async def post(self, request: Request, user_id: str):
        context = _context(request)
        require_permission(context, "platform.manage")
        user = (await request.ctx.db.execute(select(PlatformUser).where(PlatformUser.Id == user_id))).scalar_one_or_none()
        if user is None:
            raise PlatformNotFound("用户不存在")
        credential = (await request.ctx.db.execute(select(PlatformCredential).where(PlatformCredential.AccountId == user.AccountId))).scalar_one_or_none()
        if credential is None:
            raise PlatformNotFound("用户凭据不存在")
        initial_password = generate_initial_password()
        salt = _new_salt()
        credential.PasswordHash = password_hash(initial_password, salt)
        credential.PasswordSalt = salt
        credential.MustReset = True
        credential.FailedAttempts = 0
        credential.LockedUntil = None
        request.ctx.db.add(credential)
        await revoke_account_sessions(request.ctx.db, str(user.AccountId))
        await revoke_account_execution_contexts(request.ctx.db, str(user.AccountId))
        reply_tasks_revoked = await revoke_account_delivery_tasks(request.ctx.db, str(user.AccountId))
        channel_identities_revoked = await revoke_account_channel_identities(request.ctx.db, str(user.AccountId))
        await _commit_audit(request, action="user.reset_password", target_type="platform_user", target_id=str(user.Id), metadata={"sessionRevoked": True, "replyTasksRevoked": reply_tasks_revoked, "channelIdentitiesRevoked": channel_identities_revoked})
        return json({"userId": str(user.Id), "initialPassword": initial_password})


class AdminUserAccessApi(HTTPMethodView):
    """Change role and enterprise scope without exposing credentials."""

    @platform_required
    async def post(self, request: Request, user_id: str):
        context = _context(request)
        require_permission(context, "platform.manage")
        if str(context.user.Id) == str(user_id):
            raise PlatformBadRequest("不能修改当前登录账号的角色或企业范围")
        body = _body(request)
        if "role" not in body and "enterpriseIds" not in body:
            raise PlatformBadRequest("至少提供 role 或 enterpriseIds")
        if "enterpriseIds" in body and not isinstance(body["enterpriseIds"], list):
            raise PlatformBadRequest("enterpriseIds 必须是 JSON 数组")
        user, _ = await update_platform_user_access(
            request.ctx.db,
            user_id=user_id,
            role=body.get("role") if "role" in body else None,
            enterprise_ids=body.get("enterpriseIds") if "enterpriseIds" in body else None,
        )
        reply_tasks_revoked = await revoke_account_delivery_tasks(request.ctx.db, str(user.AccountId))
        channel_identities_revoked = await revoke_account_channel_identities(request.ctx.db, str(user.AccountId))
        enterprises = await get_enterprises_for_user(request.ctx.db, user)
        await _commit_audit(
            request,
            action="user.access.update",
            target_type="platform_user",
            target_id=str(user.Id),
            metadata={
                "role": user.Role,
                "enterpriseIds": [str(item.Id) for item in enterprises],
                "executionContextsRevoked": True,
                "replyTasksRevoked": reply_tasks_revoked,
                "channelIdentitiesRevoked": channel_identities_revoked,
            },
        )
        return json({
            "user": {
                **serialize_user(user),
                "status": user.Status,
                "enterprises": [
                    {
                        "id": str(item.Id),
                        "name": item.Name,
                        "customerCode": item.CustomerCode,
                        "status": item.Status,
                    }
                    for item in enterprises
                ],
            }
        })


class AdminUserDisableApi(HTTPMethodView):
    @platform_required
    async def post(self, request: Request, user_id: str):
        context = _context(request)
        require_permission(context, "platform.manage")
        if str(context.user.Id) == str(user_id):
            raise PlatformBadRequest("不能停用当前登录账号")
        user = (await request.ctx.db.execute(select(PlatformUser).where(PlatformUser.Id == user_id))).scalar_one_or_none()
        if user is None:
            raise PlatformNotFound("用户不存在")
        user.Status = PlatformStatus.DISABLED
        account = (await request.ctx.db.execute(select(Account).where(Account.Id == user.AccountId))).scalar_one_or_none()
        if account is not None:
            account.Status = AccountStatus.BANNED
        request.ctx.db.add(account)
        request.ctx.db.add(user)
        await revoke_account_sessions(request.ctx.db, str(user.AccountId))
        await revoke_account_execution_contexts(request.ctx.db, str(user.AccountId))
        reply_tasks_revoked = await revoke_account_delivery_tasks(request.ctx.db, str(user.AccountId))
        channel_identities_revoked = await revoke_account_channel_identities(request.ctx.db, str(user.AccountId))
        await _commit_audit(request, action="user.disable", target_type="platform_user", target_id=str(user.Id), metadata={"sessionRevoked": True, "replyTasksRevoked": reply_tasks_revoked, "channelIdentitiesRevoked": channel_identities_revoked})
        return json({"userId": str(user.Id), "status": user.Status})


class AdminAuditListApi(HTTPMethodView):
    @platform_required
    async def get(self, request: Request):
        require_permission(_context(request), "platform.manage")
        events = list((await request.ctx.db.execute(select(PlatformAuditEvent).order_by(PlatformAuditEvent.CreatedAt.desc()).limit(200))).scalars().all())
        return json([{
            "id": str(event.Id), "action": event.Action, "targetType": event.TargetType,
            "targetId": event.TargetId, "traceId": event.TraceId, "outcome": event.Outcome,
            "metadata": event.Metadata or {}, "createdAt": event.CreatedAt.isoformat() if event.CreatedAt else "",
        } for event in events])


class AdminChannelIdentityListApi(HTTPMethodView):
    @platform_required
    async def get(self, request: Request):
        require_permission(_context(request), "platform.manage")
        statement = select(PlatformChannelIdentity).order_by(PlatformChannelIdentity.CreatedAt.desc())
        enterprise_id = request.args.get("enterpriseId")
        if enterprise_id:
            try:
                enterprise_id = str(uuid.UUID(enterprise_id))
            except ValueError as exc:
                raise PlatformBadRequest("enterpriseId格式不正确") from exc
            statement = statement.where(PlatformChannelIdentity.EnterpriseId == enterprise_id)
        user_id = request.args.get("userId")
        if user_id:
            try:
                user_id = str(uuid.UUID(user_id))
            except ValueError as exc:
                raise PlatformBadRequest("userId格式不正确") from exc
            statement = statement.where(PlatformChannelIdentity.UserId == user_id)
        rows = list((await request.ctx.db.execute(statement)).scalars().all())
        return json([serialize_channel_identity(row) for row in rows])


class AdminChannelIdentityRevokeApi(HTTPMethodView):
    @platform_required
    async def post(self, request: Request, identity_id: str):
        context = _context(request)
        require_permission(context, "platform.manage")
        identity_id = _required_uuid({"identityId": identity_id}, "identityId")
        row = await revoke_channel_identity(request.ctx.db, identity_id=identity_id)
        await _commit_audit(
            request,
            action="channel.identity.revoke",
            target_type="platform_channel_identity",
            target_id=str(row.Id),
            metadata={
                "channel": row.Channel,
                "channelInstanceId": row.ChannelInstanceId,
                "externalIdentityFingerprint": external_identity_fingerprint(row.ExternalIdentityId),
                "admin": True,
            },
        )
        return json({"identity": serialize_channel_identity(row)})


def _serialize_binding(connection: IntegrationConnection, external: EnterpriseExternalAccount, enterprise: PlatformEnterprise) -> dict[str, Any]:
    return {
        "id": str(external.Id),
        "connectionId": str(connection.Id),
        "enterpriseId": str(enterprise.Id),
        "enterpriseName": enterprise.Name,
        "customerCode": enterprise.CustomerCode,
        "applicationId": connection.ApplicationId,
        "upstreamAppId": connection.UpstreamAppId,
        "vendor": connection.Vendor,
        "workspaceId": external.WorkspaceId,
        "externalAccountId": external.ExternalAccountId,
        "status": external.Status if connection.Status == IntegrationConnectionStatus.ACTIVE else IntegrationConnectionStatus.DISABLED,
        "connectionStatus": connection.Status,
        "createdAt": external.CreatedAt.isoformat() if external.CreatedAt else "",
        "updatedAt": external.UpdatedAt.isoformat() if external.UpdatedAt else "",
    }


def _required_uuid(body: dict[str, Any], field: str) -> str:
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        raise PlatformBadRequest(f"{field}格式不正确")
    try:
        return str(uuid.UUID(value.strip()))
    except ValueError as exc:
        raise PlatformBadRequest(f"{field}格式不正确") from exc


def _required_channel_text(body: dict[str, Any], field: str, max_length: int) -> str:
    value = body.get(field)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_length:
        raise PlatformBadRequest(f"{field}格式不正确")
    return value.strip()


async def _load_active_credential_scope(request: Request, enterprise_id: str, connection_id: str) -> tuple[PlatformEnterprise, IntegrationConnection]:
    enterprise = await request.ctx.db.get(PlatformEnterprise, enterprise_id)
    connection = await request.ctx.db.get(IntegrationConnection, connection_id)
    if enterprise is None or enterprise.Status != EnterpriseStatus.ACTIVE:
        raise PlatformNotFound("企业不存在或未启用")
    if connection is None or connection.Status != IntegrationConnectionStatus.ACTIVE:
        raise PlatformNotFound("连接不存在或未启用")
    binding = (
        await request.ctx.db.execute(
            select(EnterpriseExternalAccount).where(
                EnterpriseExternalAccount.EnterpriseId == enterprise.Id,
                EnterpriseExternalAccount.ConnectionId == connection.Id,
                EnterpriseExternalAccount.Status == IntegrationConnectionStatus.ACTIVE,
            )
        )
    ).scalar_one_or_none()
    if binding is None:
        raise PlatformNotFound("企业与连接的有效绑定不存在")
    return enterprise, connection


def _serialize_admin_credential(row: PlatformChannelCredential, enterprise: PlatformEnterprise | None = None, connection: IntegrationConnection | None = None) -> dict[str, Any]:
    payload = serialize_credential(row)
    if enterprise is not None:
        payload["enterpriseName"] = enterprise.Name
        payload["customerCode"] = enterprise.CustomerCode
    if connection is not None:
        payload["applicationId"] = connection.ApplicationId
        payload["vendor"] = connection.Vendor
    return payload


def _encrypt_for_admin(value: Any):
    try:
        return encrypt_credential(value)
    except ChannelCredentialError as exc:
        logger.warning("channel credential encryption rejected: %s", type(exc).__name__)
        raise PlatformBadRequest("渠道凭据暂不可保存，请检查加密密钥配置") from exc


class AdminChannelCredentialListApi(HTTPMethodView):
    @platform_required
    async def get(self, request: Request):
        require_permission(_context(request), "platform.manage")
        statement = (
            select(PlatformChannelCredential, PlatformEnterprise, IntegrationConnection)
            .join(PlatformEnterprise, PlatformEnterprise.Id == PlatformChannelCredential.EnterpriseId)
            .join(IntegrationConnection, IntegrationConnection.Id == PlatformChannelCredential.ConnectionId)
            .order_by(PlatformChannelCredential.UpdatedAt.desc())
        )
        enterprise_id = request.args.get("enterpriseId")
        if enterprise_id:
            try:
                enterprise_id = str(uuid.UUID(enterprise_id))
            except ValueError as exc:
                raise PlatformBadRequest("enterpriseId格式不正确") from exc
            statement = statement.where(PlatformChannelCredential.EnterpriseId == enterprise_id)
        rows = (await request.ctx.db.execute(statement)).all()
        return json([_serialize_admin_credential(row, enterprise, connection) for row, enterprise, connection in rows])

    @platform_required
    async def post(self, request: Request):
        require_permission(_context(request), "platform.manage")
        body = _body(request)
        enterprise_id = _required_uuid(body, "enterpriseId")
        connection_id = _required_uuid(body, "connectionId")
        channel = _required_channel_text(body, "channel", 48)
        channel_instance_id = _required_channel_text(body, "channelInstanceId", 128)
        if "credential" not in body:
            raise PlatformBadRequest("credential为必填项")
        enterprise, connection = await _load_active_credential_scope(request, enterprise_id, connection_id)
        existing = (
            await request.ctx.db.execute(
                select(PlatformChannelCredential).where(
                    PlatformChannelCredential.EnterpriseId == enterprise.Id,
                    PlatformChannelCredential.ConnectionId == connection.Id,
                    PlatformChannelCredential.Channel == channel,
                    PlatformChannelCredential.ChannelInstanceId == channel_instance_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise PlatformBadRequest("该企业连接的渠道凭据已存在，请使用轮换接口")
        encrypted = _encrypt_for_admin(body["credential"])
        row = PlatformChannelCredential(
            EnterpriseId=enterprise.Id,
            ConnectionId=connection.Id,
            Channel=channel,
            ChannelInstanceId=channel_instance_id,
            Ciphertext=encrypted.ciphertext,
            KeyVersion=encrypted.key_version,
            Version=1,
            Fingerprint=encrypted.fingerprint,
            Status=PlatformChannelCredentialStatus.ACTIVE,
        )
        request.ctx.db.add(row)
        await request.ctx.db.flush()
        await _commit_audit(
            request,
            action="channel.credential.create",
            target_type="platform_channel_credential",
            target_id=str(row.Id),
            metadata={"enterpriseId": str(enterprise.Id), "connectionId": str(connection.Id), "channel": channel, "version": 1, "keyVersion": encrypted.key_version},
        )
        return json(_serialize_admin_credential(row, enterprise, connection), status=201)


class AdminChannelCredentialRotateApi(HTTPMethodView):
    @platform_required
    async def post(self, request: Request, credential_id: str):
        require_permission(_context(request), "platform.manage")
        row = await request.ctx.db.get(PlatformChannelCredential, credential_id)
        if row is None:
            raise PlatformNotFound("渠道凭据不存在")
        if row.Status != PlatformChannelCredentialStatus.ACTIVE:
            raise PlatformBadRequest("停用的渠道凭据不能轮换")
        body = _body(request)
        if "credential" not in body:
            raise PlatformBadRequest("credential为必填项")
        enterprise, connection = await _load_active_credential_scope(request, str(row.EnterpriseId), str(row.ConnectionId))
        credential_value = body["credential"]
        # Token-only rotation must not silently downgrade an encrypted WeChat
        # instance back to plaintext mode. Preserve the existing non-token
        # fields unless the caller explicitly supplies replacements.
        if row.Channel == WECHAT_OFFICIAL_ACCOUNT and isinstance(credential_value, str):
            incoming = _wechat_credential(credential_value)
            try:
                previous = _wechat_credential(decrypt_credential(row))
            except ChannelCredentialError as exc:
                raise PlatformBadRequest("微信服务号旧凭据无法读取，请重新配置完整凭据") from exc
            for key in ("appId", "app_id", "appSecret", "app_secret", "encodingAesKey", "encoding_aes_key"):
                if key not in incoming and key in previous:
                    incoming[key] = previous[key]
            credential_value = stdlib_json.dumps(incoming, ensure_ascii=False, separators=(",", ":"))
        encrypted = _encrypt_for_admin(credential_value)
        row.Ciphertext = encrypted.ciphertext
        row.KeyVersion = encrypted.key_version
        row.Fingerprint = encrypted.fingerprint
        row.Version = int(row.Version or 1) + 1
        row.RotatedAt = utc_now()
        request.ctx.db.add(row)
        await _commit_audit(
            request,
            action="channel.credential.rotate",
            target_type="platform_channel_credential",
            target_id=str(row.Id),
            metadata={"enterpriseId": str(row.EnterpriseId), "connectionId": str(row.ConnectionId), "channel": row.Channel, "version": row.Version, "keyVersion": row.KeyVersion},
        )
        return json(_serialize_admin_credential(row, enterprise, connection))


class AdminChannelCredentialDisableApi(HTTPMethodView):
    @platform_required
    async def post(self, request: Request, credential_id: str):
        require_permission(_context(request), "platform.manage")
        row = await request.ctx.db.get(PlatformChannelCredential, credential_id)
        if row is None:
            raise PlatformNotFound("渠道凭据不存在")
        row.Status = PlatformChannelCredentialStatus.DISABLED
        request.ctx.db.add(row)
        await _commit_audit(
            request,
            action="channel.credential.disable",
            target_type="platform_channel_credential",
            target_id=str(row.Id),
            metadata={"enterpriseId": str(row.EnterpriseId), "connectionId": str(row.ConnectionId), "channel": row.Channel, "version": row.Version},
        )
        return json(_serialize_admin_credential(row))


class AdminBindingListApi(HTTPMethodView):
    @platform_required
    async def get(self, request: Request):
        require_permission(_context(request), "platform.manage")
        rows = (
            await request.ctx.db.execute(
                select(IntegrationConnection, EnterpriseExternalAccount, PlatformEnterprise)
                .join(EnterpriseExternalAccount, EnterpriseExternalAccount.ConnectionId == IntegrationConnection.Id)
                .join(PlatformEnterprise, PlatformEnterprise.Id == EnterpriseExternalAccount.EnterpriseId)
                .order_by(PlatformEnterprise.Name, IntegrationConnection.ApplicationId)
            )
        ).all()
        return json([_serialize_binding(connection, external, enterprise) for connection, external, enterprise in rows])

    @platform_required
    async def post(self, request: Request):
        context = _context(request)
        require_permission(context, "platform.manage")
        body = _body(request)
        application_id = str(body.get("applicationId") or "").strip()
        upstream_app_id = str(body.get("upstreamAppId") or "").strip()
        enterprise_id = str(body.get("enterpriseId") or "").strip()
        workspace_id = str(body.get("workspaceId") or "").strip()
        external_account_id = str(body.get("externalAccountId") or "").strip()
        if not application_id or not upstream_app_id or not enterprise_id or not workspace_id or not external_account_id:
            raise PlatformBadRequest("applicationId、upstreamAppId、enterpriseId、workspaceId、externalAccountId 均为必填")
        if application_id not in app.apps:
            raise PlatformNotFound("应用不存在或未配置")
        enterprise = await request.ctx.db.get(PlatformEnterprise, enterprise_id)
        if enterprise is None or enterprise.Status != EnterpriseStatus.ACTIVE:
            raise PlatformNotFound("企业不存在或未启用")
        connection = (
            await request.ctx.db.execute(
                select(IntegrationConnection).where(IntegrationConnection.ApplicationId == application_id)
            )
        ).scalar_one_or_none()
        if connection is None:
            vendor = str(body.get("vendor") or getattr(app.apps[application_id], "config", {}).get("Vendor") or "unknown")[:64]
            connection = IntegrationConnection(
                ApplicationId=application_id,
                UpstreamAppId=upstream_app_id,
                Vendor=vendor,
                Status=IntegrationConnectionStatus.ACTIVE,
            )
            request.ctx.db.add(connection)
            await request.ctx.db.flush()
        else:
            connection.UpstreamAppId = upstream_app_id
            connection.Status = IntegrationConnectionStatus.ACTIVE
            request.ctx.db.add(connection)

        external = (
            await request.ctx.db.execute(
                select(EnterpriseExternalAccount).where(
                    EnterpriseExternalAccount.EnterpriseId == enterprise.Id,
                    EnterpriseExternalAccount.ConnectionId == connection.Id,
                )
            )
        ).scalar_one_or_none()
        if external is None:
            external = EnterpriseExternalAccount(
                EnterpriseId=enterprise.Id,
                ConnectionId=connection.Id,
                ExternalAccountId=external_account_id,
                WorkspaceId=workspace_id,
                Status=IntegrationConnectionStatus.ACTIVE,
            )
        else:
            external.ExternalAccountId = external_account_id
            external.WorkspaceId = workspace_id
            external.Status = IntegrationConnectionStatus.ACTIVE
        request.ctx.db.add(external)
        await _commit_audit(
            request,
            action="integration.binding.upsert",
            target_type="enterprise_external_account",
            target_id=str(external.Id),
            metadata={"enterpriseId": str(enterprise.Id), "applicationId": application_id, "workspaceId": workspace_id},
        )
        return json(_serialize_binding(connection, external, enterprise), status=201)


class AdminBindingDisableApi(HTTPMethodView):
    @platform_required
    async def post(self, request: Request, binding_id: str):
        context = _context(request)
        require_permission(context, "platform.manage")
        external = await request.ctx.db.get(EnterpriseExternalAccount, binding_id)
        if external is None:
            raise PlatformNotFound("绑定不存在")
        external.Status = IntegrationConnectionStatus.DISABLED
        request.ctx.db.add(external)
        await _commit_audit(
            request,
            action="integration.binding.disable",
            target_type="enterprise_external_account",
            target_id=str(external.Id),
            metadata={"enterpriseId": str(external.EnterpriseId), "connectionId": str(external.ConnectionId)},
        )
        return json({"id": str(external.Id), "status": external.Status})


app.add_route(PlatformLoginApi.as_view(), "/api/v1/auth/login")
app.add_route(PlatformLogoutApi.as_view(), "/api/v1/auth/logout")
app.add_route(PlatformSessionApi.as_view(), "/api/v1/auth/session")
app.add_route(PortalOverviewApi.as_view(), "/api/v1/portal/overview")
app.add_route(PortalSessionsApi.as_view(), "/api/v1/portal/sessions")
app.add_route(PortalSessionDetailApi.as_view(), "/api/v1/portal/sessions/<conversation_id:str>")
app.add_route(ShipmentLookupApi.as_view(), "/api/v1/tools/shipment/lookup")
app.add_route(WebChannelInboundApi.as_view(), "/api/v1/channels/web/inbound")
app.add_route(WebChannelInboundStatusApi.as_view(), "/api/v1/channels/web/inbound/<inbound_id:str>")
app.add_route(
    WechatOfficialAccountCallbackApi.as_view(),
    "/api/v1/channels/wechat-official-account/<channel_instance_id:str>/callback",
)
app.add_route(WechatOfficialAccountFixedCallbackApi.as_view(), "/wechat/callback", name="wechat_fixed_callback")
app.add_route(
    WechatOfficialAccountFixedCallbackApi.as_view(),
    "/api/v1/channels/wechat-official-account/callback",
    name="wechat_official_account_fixed_callback",
)
app.add_route(ChannelIdentityBindApi.as_view(), "/api/v1/channel-identities")
app.add_route(ChannelIdentityRevokeApi.as_view(), "/api/v1/channel-identities/<identity_id:str>/revoke")
app.add_route(PlatformInboundApi.as_view(), "/api/internal/platform/inbound")
app.add_route(AdpExecutionContextApi.as_view(), "/api/internal/adp/execution-context")
app.add_route(AdminAdpChatContextApi.as_view(), "/api/v1/admin/adp-chat/context")
app.add_route(AdpShipmentLookupApi.as_view(), "/api/internal/adp/tools/shipment/lookup")
app.add_route(ChannelIdentityConfirmApi.as_view(), "/api/internal/channel-identities/confirm")
app.add_route(OpsStatusApi.as_view(), "/api/v1/ops/status")
app.add_route(AdminOverviewApi.as_view(), "/api/v1/admin/overview")
app.add_route(AdminConfigApi.as_view(), "/api/v1/admin/config")
app.add_route(AdminConfigDraftApi.as_view(), "/api/v1/admin/config/draft")
app.add_route(AdminConfigPublishApi.as_view(), "/api/v1/admin/config/publish")
app.add_route(AdminConfigRollbackApi.as_view(), "/api/v1/admin/config/rollback")
app.add_route(AdminEnterpriseListApi.as_view(), "/api/v1/admin/enterprises")
app.add_route(AdminUserListApi.as_view(), "/api/v1/admin/users")
app.add_route(AdminUserResetPasswordApi.as_view(), "/api/v1/admin/users/<user_id:str>/reset-password")
app.add_route(AdminUserAccessApi.as_view(), "/api/v1/admin/users/<user_id:str>/access")
app.add_route(AdminUserDisableApi.as_view(), "/api/v1/admin/users/<user_id:str>/disable")
app.add_route(AdminAuditListApi.as_view(), "/api/v1/admin/audit")
app.add_route(AdminChannelIdentityListApi.as_view(), "/api/v1/admin/channel-identities")
app.add_route(AdminChannelIdentityRevokeApi.as_view(), "/api/v1/admin/channel-identities/<identity_id:str>/revoke")
app.add_route(AdminBindingListApi.as_view(), "/api/v1/admin/bindings")
app.add_route(AdminBindingDisableApi.as_view(), "/api/v1/admin/bindings/<binding_id:str>/disable")
app.add_route(AdminChannelCredentialListApi.as_view(), "/api/v1/admin/channel-credentials")
app.add_route(AdminChannelCredentialRotateApi.as_view(), "/api/v1/admin/channel-credentials/<credential_id:str>/rotate")
app.add_route(AdminChannelCredentialDisableApi.as_view(), "/api/v1/admin/channel-credentials/<credential_id:str>/disable")
