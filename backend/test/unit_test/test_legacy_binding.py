"""Focused authorization tests for the legacy application/workspace binding."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sanic.exceptions import SanicException

from core.legacy_binding import list_legacy_bindings, resolve_legacy_binding
from model.account import Account, AccountRole, AccountStatus, AccountThirdParty
from model.platform import (
    EnterpriseExternalAccount,
    EnterpriseStatus,
    IntegrationConnection,
    IntegrationConnectionStatus,
    PlatformEnterprise,
    PlatformUser,
)


class _Values:
    def __init__(self, values):
        self._values = list(values)

    def all(self):
        return self._values


class _Result:
    def __init__(self, *, values=(), scalar=None, rows=()):
        self._values = list(values)
        self._scalar = scalar
        self._rows = list(rows)

    def scalars(self):
        return _Values(self._values)

    def scalar_one_or_none(self):
        return self._scalar

    def all(self):
        return self._rows


class _BindingDb:
    """Small statement-aware fake so these tests do not require PostgreSQL."""

    def __init__(self, *, account, customer_codes=(), platform_user_id=None, rows=()):
        self.account = account
        self.customer_codes = list(customer_codes)
        self.platform_user_id = platform_user_id
        self.rows = list(rows)

    async def execute(self, statement):
        descriptions = statement.column_descriptions
        first = descriptions[0]["expr"]
        entity = getattr(first, "class_", None)
        if entity is AccountThirdParty:
            return _Result(values=self.customer_codes)
        if entity is PlatformUser:
            return _Result(scalar=self.platform_user_id)
        if entity is PlatformEnterprise and len(descriptions) == 1:
            return _Result(values=[enterprise.Id for _, _, enterprise in self.rows])

        params = statement.compile().params
        values = [
            item
            for value in params.values()
            for item in (value if isinstance(value, (list, tuple, set)) else [value])
        ]
        requested_app = next(
            (value for value in values if value in {"app-a", "app-b"}),
            None,
        )
        requested_workspace = next(
            (value for value in values if value in {"workspace-a", "workspace-b"}),
            None,
        )
        rows = [
            (connection, external, enterprise)
            for connection, external, enterprise in self.rows
            if connection.Status == IntegrationConnectionStatus.ACTIVE
            and external.Status == IntegrationConnectionStatus.ACTIVE
            and enterprise.Status == EnterpriseStatus.ACTIVE
            and (not self.customer_codes or enterprise.CustomerCode in self.customer_codes)
            and (requested_app is None or connection.ApplicationId == requested_app)
            and (requested_workspace is None or external.WorkspaceId == requested_workspace)
        ]
        return _Result(rows=rows)

    async def get(self, model, _identity):
        return self.account if model is Account else None


def _request(db, account_id: str):
    return SimpleNamespace(ctx=SimpleNamespace(db=db, account_id=account_id))


def _app():
    return SimpleNamespace(
        apps={
            "app-a": SimpleNamespace(config={"AppId": "upstream-a", "Vendor": "Tencent"}),
            "app-b": SimpleNamespace(config={"AppId": "upstream-b", "Vendor": "Tencent"}),
        }
    )


def _rows():
    enterprise_a = PlatformEnterprise(
        Id="00000000-0000-0000-0000-0000000000a1",
        Name="企业 A",
        CustomerCode="customer-a",
        Status=EnterpriseStatus.ACTIVE,
    )
    enterprise_b = PlatformEnterprise(
        Id="00000000-0000-0000-0000-0000000000b1",
        Name="企业 B",
        CustomerCode="customer-b",
        Status=EnterpriseStatus.ACTIVE,
    )
    connection_a = IntegrationConnection(
        Id="00000000-0000-0000-0000-0000000000c1",
        ApplicationId="app-a",
        UpstreamAppId="upstream-a",
        Vendor="Tencent",
        Status=IntegrationConnectionStatus.ACTIVE,
    )
    connection_b = IntegrationConnection(
        Id="00000000-0000-0000-0000-0000000000c2",
        ApplicationId="app-b",
        UpstreamAppId="upstream-b",
        Vendor="Tencent",
        Status=IntegrationConnectionStatus.ACTIVE,
    )
    external_a = EnterpriseExternalAccount(
        Id="00000000-0000-0000-0000-0000000000d1",
        EnterpriseId=enterprise_a.Id,
        ConnectionId=connection_a.Id,
        ExternalAccountId="external-a",
        WorkspaceId="workspace-a",
        Status=IntegrationConnectionStatus.ACTIVE,
    )
    external_b = EnterpriseExternalAccount(
        Id="00000000-0000-0000-0000-0000000000d2",
        EnterpriseId=enterprise_b.Id,
        ConnectionId=connection_b.Id,
        ExternalAccountId="external-b",
        WorkspaceId="workspace-b",
        Status=IntegrationConnectionStatus.ACTIVE,
    )
    return [
        (connection_a, external_a, enterprise_a),
        (connection_b, external_b, enterprise_b),
    ]


@pytest.mark.asyncio
async def test_binding_limits_application_workspace_and_application_list():
    rows = _rows()
    account = Account(
        Id="00000000-0000-0000-0000-000000000001",
        Name="企业 A 用户",
        Role=AccountRole.NORMAL,
        Status=AccountStatus.ACTIVE,
    )
    db = _BindingDb(account=account, customer_codes=["customer-a"], rows=rows)
    request = _request(db, str(account.Id))

    binding = await resolve_legacy_binding(request, _app(), application_id="app-a")
    assert binding.application_id == "app-a"
    assert binding.workspace_id == "workspace-a"

    with pytest.raises(SanicException) as wrong_application:
        await resolve_legacy_binding(request, _app(), application_id="app-b")
    assert wrong_application.value.status_code == 403

    with pytest.raises(SanicException) as wrong_workspace:
        await resolve_legacy_binding(
            request,
            _app(),
            application_id="app-a",
            workspace_id="workspace-b",
            require_workspace=True,
        )
    assert wrong_workspace.value.status_code == 403

    visible = await list_legacy_bindings(request, _app())
    assert [item.application_id for item in visible] == ["app-a"]


@pytest.mark.asyncio
async def test_disabled_binding_is_immediately_rejected():
    rows = _rows()
    rows[0][1].Status = IntegrationConnectionStatus.DISABLED
    account = Account(
        Id="00000000-0000-0000-0000-000000000002",
        Name="已解绑用户",
        Role=AccountRole.NORMAL,
        Status=AccountStatus.ACTIVE,
    )
    request = _request(
        _BindingDb(account=account, customer_codes=["customer-a"], rows=rows),
        str(account.Id),
    )

    with pytest.raises(SanicException) as error:
        await resolve_legacy_binding(request, _app(), application_id="app-a")
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_unbound_normal_account_is_rejected_but_active_admin_keeps_debug_fallback():
    normal = Account(
        Id="00000000-0000-0000-0000-000000000003",
        Name="未绑定用户",
        Role=AccountRole.NORMAL,
        Status=AccountStatus.ACTIVE,
    )
    app = _app()
    normal_request = _request(_BindingDb(account=normal), str(normal.Id))
    with pytest.raises(SanicException) as normal_error:
        await resolve_legacy_binding(normal_request, app, application_id="app-a")
    assert normal_error.value.status_code == 403

    admin = Account(
        Id="00000000-0000-0000-0000-000000000004",
        Name="本地管理员",
        Role=AccountRole.ADMIN,
        Status=AccountStatus.ACTIVE,
    )
    admin_request = _request(_BindingDb(account=admin), str(admin.Id))
    fallback = await resolve_legacy_binding(admin_request, app, application_id="app-a")
    assert fallback.application_id == "app-a"
    assert fallback.upstream_app_id == "upstream-a"
    assert fallback.external_account is None

    admin.Status = AccountStatus.BANNED
    with pytest.raises(SanicException) as banned_error:
        await resolve_legacy_binding(admin_request, app, application_id="app-a")
    assert banned_error.value.status_code == 403
