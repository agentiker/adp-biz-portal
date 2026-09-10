"""Security helpers for the legacy ADP compatibility routes.

The legacy client still sends vendor-facing identifiers, but those values are
not an authority boundary.  This module keeps the compatibility surface small:
configured applications are the only selectable vendors, normal accounts may
only use read actions, and local conversation ownership is always resolved
from the database.
"""

from __future__ import annotations

from functools import wraps
from typing import Any

from sanic.exceptions import SanicException

from core.account import CoreAccount
from core.conversation import CoreConversation
from model.account import AccountRole
from router import check_login
from util.database import db_connection


# Actions used by the existing chat component that are safe for a normal
# account. Unknown actions are intentionally denied even when they look
# read-only.
LEGACY_READ_ACTIONS = frozenset(
    {
        "DescribeConversation",
        "DescribeConversationMessageList",
        "ListModel",
        "DescribeAgentDetail",
        "DescribeAgentSummaryList",
        "FetchFile",
        "ListDir",
        "DescribeKnowledges",
        "ListReferShareKnowledge",
        "GetKBDefaultConfig",
        "DescribePluginSummaryList",
        "DescribePlugin",
        "DescribePluginCategoryList",
        "CreatePluginOAuthUrl",
        "DescribeSkillCategoryList",
        "DescribeSkillSummaryList",
    }
)

# These APIs expose channel/configuration objects and their execution logs.
# They are read-only from the vendor's perspective, but still belong to the
# management plane and may contain data for other users or channels.
LEGACY_ADMIN_READ_ACTIONS = frozenset(
    {
        "DescribeConversationList",
        "DescribeChannel",
        "DescribeChannelList",
        "DescribeTimerTask",
        "DescribeTimerTaskSummaryList",
        "DescribeTimerTaskRunLogList",
        "DescribeAppTrigger",
        "DescribeAppTriggerSummaryList",
        "DescribeAppTriggerInstance",
        "DescribeAppTriggerRunLogList",
    }
)

# Management actions are retained only for legacy admin accounts.  This list
# is explicit so an arbitrary vendor API cannot be reached through /adp.
LEGACY_ADMIN_ACTIONS = frozenset(
    {
        "CreateChannel",
        "ModifyChannel",
        "DeleteChannel",
        "CreateConversation",
        "CopyAgentFromApp",
        "ModifyAgent",
        "BindAgentTool",
        "UnbindAgentTool",
        "ModifyAgentToolList",
        "CreateTimerTask",
        "ModifyTimerTask",
        "DeleteTimerTask",
        "PauseTimerTask",
        "ResumeTimerTask",
        "RunTimerTaskNow",
        "MarkTimerTaskRunLogRead",
        "CreateAppTrigger",
        "ModifyAppTrigger",
        "DeleteAppTrigger",
        "PauseAppTrigger",
        "ResumeAppTrigger",
        "RunAppTriggerNow",
        "MarkAppTriggerRunLogRead",
    }
)

LEGACY_FILE_ACTIONS = frozenset({"FetchFile", "ListDir"})


def require_configured_application(app: Any, application_id: str):
    """Return a configured vendor or reject a client-supplied app id."""
    if not isinstance(application_id, str) or not application_id.strip():
        raise SanicException("ApplicationId is required", status_code=400)
    if len(application_id) > 64 or application_id not in app.apps:
        raise SanicException("application is not available", status_code=404)
    return app.apps[application_id]


def validate_workspace_file_payload(
    payload: dict[str, Any],
    vendor_app: Any,
    application_id: str,
    *,
    require_workspace: bool = True,
    binding: Any | None = None,
) -> dict[str, Any]:
    """Validate the vendor-facing workspace fields used by file APIs.

    The old client sends ``app_id`` and ``workspace_id`` directly to the
    vendor.  They are not an authorization boundary, so ``app_id`` must agree
    with the configured vendor application and filesystem values must be
    bounded before they reach the upstream filesystem API.  A local mapping
    from account to upstream workspace is not available yet; that remaining
    tenant-boundary gap is tracked in the roadmap.
    """
    values = dict(payload or {})
    configured_app_id = (
        getattr(binding, "upstream_app_id", None)
        if binding is not None
        else getattr(vendor_app, "config", {}).get("AppId") or application_id
    )
    app_id = values.get("app_id")
    if not isinstance(app_id, str) or not app_id.strip():
        raise SanicException("app_id is required", status_code=400)
    if app_id != configured_app_id:
        raise SanicException("file application mismatch", status_code=403)

    workspace_id = values.get("workspace_id")
    if require_workspace and (not isinstance(workspace_id, str) or not workspace_id.strip()):
        raise SanicException("workspace_id is required", status_code=400)
    if workspace_id is not None:
        if not isinstance(workspace_id, str) or len(workspace_id) > 256:
            raise SanicException("invalid workspace_id", status_code=400)
        if any(ord(char) < 32 or ord(char) == 127 for char in workspace_id):
            raise SanicException("invalid workspace_id", status_code=400)
        if binding is not None and binding.workspace_id != workspace_id:
            raise SanicException("workspace does not belong to current enterprise", status_code=403)

    file_path = values.get("path")
    if not isinstance(file_path, str) or not file_path.strip():
        raise SanicException("path is required", status_code=400)
    if len(file_path) > 2048 or "\\" in file_path:
        raise SanicException("invalid path", status_code=400)
    if any(ord(char) < 32 or ord(char) == 127 for char in file_path):
        raise SanicException("invalid path", status_code=400)
    if ".." in file_path.split("/"):
        raise SanicException("path traversal is not allowed", status_code=400)

    return values


async def legacy_account_is_admin(request) -> bool:
    """Resolve the old account role from the database, never from the token."""
    request_db = getattr(request.ctx, "db", None)
    if request_db is not None:
        account = await CoreAccount.get(request_db, request.ctx.account_id)
    else:
        # Streaming compatibility routes intentionally skip the request-scoped
        # session middleware; use a short-lived session for the authorization
        # lookup instead.
        async with db_connection() as db:
            account = await CoreAccount.get(db, request.ctx.account_id)
    if account is None:
        raise SanicException("account not found", status_code=401)
    return account.Role == AccountRole.ADMIN


async def require_legacy_admin(request) -> None:
    if not await legacy_account_is_admin(request):
        raise SanicException("管理员权限 required", status_code=403)


def adp_admin_required(view):
    """Gate every route that reaches the ADP vendor behind an administrator.

    The ADP debugger under `/admin/adp-chat` is the only remaining consumer of
    these compatibility routes, and that page is itself behind `platform.manage`.
    Requiring an administrator here closes two gaps that `login_required` alone
    left open:

    * `LEGACY_READ_ACTIONS` used to be reachable by any `login_token` holder, so
      a non-administrator could read ADP agent/plugin/skill/knowledge metadata
      through `/adp/<action>` using the platform's own vendor credentials.
    * `AccountInfoApi` auto-registers a visitor and issues a `login_token` when
      `AUTO_CREATE_ACCOUNT` is enabled.  Those accounts default to
      `AccountRole.NORMAL`, so they are now rejected before reaching the vendor.

    The role is read from the database by `legacy_account_is_admin`, never from
    the token.  Platform administrators already carry `AccountRole.ADMIN`
    because `core.platform` keeps both role fields in sync on create and on
    role change.
    """

    @wraps(view)
    async def decorated(*args, **kwargs):
        _, request = args
        check_login(request)
        await require_legacy_admin(request)
        return await view(*args, **kwargs)

    return decorated


def require_allowed_action(action: str, is_admin: bool) -> None:
    if action in LEGACY_READ_ACTIONS:
        return
    if action in LEGACY_ADMIN_READ_ACTIONS:
        if is_admin:
            return
        raise SanicException("该兼容接口需要管理员权限", status_code=403)
    if is_admin and action in LEGACY_ADMIN_ACTIONS:
        return
    raise SanicException("该兼容接口不允许执行此 Action", status_code=403)


async def application_for_conversation(
    request,
    conversation_id: str,
    supplied_application_id: str | None = None,
) -> str:
    """Resolve an owned conversation's application and reject mismatches."""
    if not isinstance(conversation_id, str) or not conversation_id.strip():
        raise SanicException("ConversationId is required", status_code=400)
    request_db = getattr(request.ctx, "db", None)
    if request_db is not None:
        application_id = await CoreConversation.get_application_id(
            request_db,
            request.ctx.account_id,
            conversation_id,
        )
    else:
        async with db_connection() as db:
            application_id = await CoreConversation.get_application_id(
                db,
                request.ctx.account_id,
                conversation_id,
            )
    if supplied_application_id and supplied_application_id != application_id:
        raise SanicException("conversation application mismatch", status_code=403)
    return application_id


def sanitize_legacy_payload(payload: dict[str, Any], account_id: str, action: str) -> dict[str, Any]:
    """Prevent identity fields in generic ADP payloads from changing scope."""
    sanitized = dict(payload or {})
    for key in ("AccountId", "VisitorId", "CustomerId", "OpenId", "UserId"):
        sanitized.pop(key, None)
    if action in {"DescribeConversationList", "DescribeConversationMessageList"}:
        # The legacy ADP templates use ACCOUNT_ID when UserId is omitted.  Set
        # it explicitly after removing the client value to avoid cross-user
        # conversation queries when a vendor accepts an optional UserId.
        sanitized["UserId"] = account_id
    return sanitized
