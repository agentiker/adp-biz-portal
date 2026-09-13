"""Server-side bindings for the legacy ADP compatibility surface.

The legacy client still sends vendor identifiers for backwards compatibility,
but those values are selectors only.  Authorization comes from the account's
enterprise scope and the active connection/workspace rows below.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sanic.exceptions import SanicException
from sqlalchemy import select

from model.account import Account, AccountStatus, AccountThirdParty
from model.platform import (
    EnterpriseExternalAccount,
    EnterpriseStatus,
    IntegrationConnection,
    IntegrationConnectionStatus,
    PlatformEnterprise,
    PlatformMembership,
    PlatformUser,
)


@dataclass(frozen=True)
class LegacyBinding:
    connection: IntegrationConnection
    external_account: EnterpriseExternalAccount | None
    enterprise: PlatformEnterprise | None
    vendor_app: Any

    @property
    def application_id(self) -> str:
        return self.connection.ApplicationId

    @property
    def upstream_app_id(self) -> str:
        return self.connection.UpstreamAppId

    @property
    def workspace_id(self) -> str | None:
        return self.external_account.WorkspaceId if self.external_account else None


async def _enterprise_ids(db, account_id: str) -> list[str]:
    """Resolve active enterprises for both legacy and platform accounts."""
    ids: set[str] = set()
    customer = (
        await db.execute(
            select(AccountThirdParty.OpenId)
            .join(Account, Account.Id == AccountThirdParty.AccountId)
            .where(
                AccountThirdParty.AccountId == account_id,
                AccountThirdParty.Provider == "customer",
                Account.Status == AccountStatus.ACTIVE,
            )
        )
    ).scalars().all()
    if customer:
        rows = (
            await db.execute(
                select(PlatformEnterprise.Id).where(
                    PlatformEnterprise.CustomerCode.in_(customer),
                    PlatformEnterprise.Status == EnterpriseStatus.ACTIVE,
                )
            )
        ).scalars().all()
        ids.update(str(item) for item in rows)

    platform_user = (
        await db.execute(
            select(PlatformUser.Id)
            .join(Account, Account.Id == PlatformUser.AccountId)
            .where(
                PlatformUser.AccountId == account_id,
                PlatformUser.Status == "active",
                Account.Status == AccountStatus.ACTIVE,
            )
        )
    ).scalar_one_or_none()
    if platform_user is not None:
        rows = (
            await db.execute(
                select(PlatformEnterprise.Id)
                .join(PlatformMembership, PlatformMembership.EnterpriseId == PlatformEnterprise.Id)
                .where(
                    PlatformMembership.UserId == platform_user,
                    PlatformMembership.Active.is_(True),
                    PlatformEnterprise.Status == EnterpriseStatus.ACTIVE,
                )
            )
        ).scalars().all()
        ids.update(str(item) for item in rows)
    return sorted(ids)


async def _is_admin(db, account_id: str) -> bool:
    from model.account import Account, AccountRole

    account = await db.get(Account, account_id)
    return (
        account is not None
        and account.Status == AccountStatus.ACTIVE
        and account.Role == AccountRole.ADMIN
    )


async def _db_for_request(request):
    request_db = getattr(request.ctx, "db", None)
    if request_db is not None:
        return request_db, False
    from util.database import db_connection

    return db_connection(), True


async def resolve_legacy_bindings(
    request,
    app,
    *,
    application_id: str | None = None,
    workspace_id: str | None = None,
    require_workspace: bool = False,
    allow_admin_fallback: bool = True,
) -> list[LegacyBinding]:
    """Return active bindings visible to the authenticated legacy account."""
    if application_id is not None and (not isinstance(application_id, str) or not application_id.strip()):
        raise SanicException("ApplicationId is required", status_code=400)

    db = getattr(request.ctx, "db", None)
    close_db = False
    manager = None
    if db is None:
        from util.database import db_connection

        manager = db_connection()
        db = await manager.__aenter__()
        close_db = True
    try:
        enterprise_ids = await _enterprise_ids(db, request.ctx.account_id)
        admin_fallback = allow_admin_fallback and not enterprise_ids and await _is_admin(db, request.ctx.account_id)

        stmt = (
            select(IntegrationConnection, EnterpriseExternalAccount, PlatformEnterprise)
            .join(
                EnterpriseExternalAccount,
                EnterpriseExternalAccount.ConnectionId == IntegrationConnection.Id,
            )
            .join(PlatformEnterprise, PlatformEnterprise.Id == EnterpriseExternalAccount.EnterpriseId)
            .where(
                IntegrationConnection.Status == IntegrationConnectionStatus.ACTIVE,
                EnterpriseExternalAccount.Status == IntegrationConnectionStatus.ACTIVE,
                PlatformEnterprise.Status == EnterpriseStatus.ACTIVE,
            )
        )
        if application_id is not None:
            stmt = stmt.where(IntegrationConnection.ApplicationId == application_id)
        if enterprise_ids:
            stmt = stmt.where(EnterpriseExternalAccount.EnterpriseId.in_(enterprise_ids))
        else:
            stmt = stmt.where(False)
        rows = (await db.execute(stmt)).all()

        bindings = [
            LegacyBinding(connection, external, enterprise, app.apps.get(connection.ApplicationId))
            for connection, external, enterprise in rows
            if connection.ApplicationId in app.apps
        ]

        if not bindings and admin_fallback and application_id in app.apps:
            vendor_app = app.apps[application_id]
            config = getattr(vendor_app, "config", {}) or {}
            connection = IntegrationConnection(
                ApplicationId=application_id,
                UpstreamAppId=str(config.get("AppId") or application_id),
                Vendor=str(config.get("Vendor") or "unknown"),
            )
            bindings = [LegacyBinding(connection, None, None, vendor_app)]

        if not bindings:
            if enterprise_ids:
                raise SanicException("应用未绑定到当前企业", status_code=403)
            raise SanicException("账号未绑定企业或上游应用", status_code=403)

        if workspace_id is not None:
            if not isinstance(workspace_id, str) or not workspace_id.strip():
                raise SanicException("WorkspaceId is required", status_code=400)
            bindings = [item for item in bindings if item.workspace_id == workspace_id]
            if not bindings:
                raise SanicException("Workspace 不属于当前企业", status_code=403)
        elif require_workspace and any(item.workspace_id is None for item in bindings):
            raise SanicException("WorkspaceId is required", status_code=400)
        return bindings
    finally:
        if close_db and manager is not None:
            await manager.__aexit__(None, None, None)


async def resolve_legacy_binding(request, app, **kwargs) -> LegacyBinding:
    bindings = await resolve_legacy_bindings(request, app, **kwargs)
    if len(bindings) > 1:
        raise SanicException("ApplicationId is required when multiple applications are available", status_code=400)
    return bindings[0]


async def list_legacy_bindings(request, app) -> list[LegacyBinding]:
    bindings: list[LegacyBinding] = []
    for application_id in app.apps:
        try:
            bindings.extend(
                await resolve_legacy_bindings(
                    request,
                    app,
                    application_id=application_id,
                )
            )
        except SanicException as error:
            if error.status_code in {403, 404}:
                continue
            raise
    if not bindings:
        raise SanicException("账号未绑定企业或上游应用", status_code=403)
    return bindings
