from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from datetime import timedelta
import uuid

import pytest

from core.error.account import AccountUnauthorized
from core.error.platform import PlatformBadRequest, PlatformForbidden, PlatformNotFound
from core.platform import (
    DEFAULT_PLATFORM_CONFIG,
    default_platform_config_payload,
    execution_token_hash,
    load_execution_context,
    permissions_for_role,
    publish_platform_config,
    rollback_platform_config,
    require_permission,
    save_platform_config_draft,
    update_platform_user_access,
    utc_now,
    validate_platform_config,
)
from model.account import Account, AccountRole
from model.platform import (
    EnterpriseStatus,
    PlatformConfigVersion,
    PlatformAuthSession,
    PlatformExecutionContext,
    PlatformEnterprise,
    PlatformMembership,
    PlatformToolDefinition,
    PlatformRole,
    PlatformUser,
)


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        if isinstance(self.value, list):
            return self.value
        return [] if self.value is None else [self.value]


def session_with(*results):
    session = SimpleNamespace(
        execute=AsyncMock(side_effect=[ScalarResult(item) for item in results]),
        add=Mock(),
        flush=AsyncMock(),
    )
    return session


def valid_payload(**overrides):
    payload = default_platform_config_payload()
    payload.update(overrides)
    return payload


def platform_user_and_account(*, role=PlatformRole.CUSTOMER):
    account_id = str(uuid.uuid4())
    user = PlatformUser(
        Id=str(uuid.uuid4()),
        AccountId=account_id,
        Name="测试用户",
        PhoneNormalized="13800000000",
        PhoneMasked="138****0000",
        Role=role,
        Status="active",
    )
    account = Account(
        Id=account_id,
        Name="测试用户",
        Role=AccountRole.ADMIN if role == PlatformRole.ADMIN else AccountRole.NORMAL,
        Status="active",
    )
    return user, account


def test_default_platform_config_is_a_deep_copy():
    payload = default_platform_config_payload()
    payload["items"].append("临时能力")
    payload["featureFlags"]["portal"] = False

    assert DEFAULT_PLATFORM_CONFIG["items"] == ["客户登录与会话", "M3 只读工具", "企业隔离", "审计记录"]
    assert DEFAULT_PLATFORM_CONFIG["featureFlags"]["portal"] is True


def test_validate_platform_config_normalizes_values_and_defaults_flags():
    payload, errors = validate_platform_config({
        "items": ["  提单查询  "],
        "featureFlags": {"portal": False},
        "notes": "  这是一条备注  ",
    })

    assert errors == []
    assert payload == {
        "items": ["提单查询"],
        "featureFlags": {
            "portal": False,
            "m3ReadOnly": True,
            "audit": True,
            "webChannel": True,
        },
        "notes": "这是一条备注",
    }


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (None, "配置必须是 JSON 对象"),
        ({"items": []}, "配置能力列表不能为空"),
        ({"items": ["查询", "查询"]}, "配置能力列表不能包含重复项"),
        ({"items": ["查询"], "unexpected": True}, "不支持的配置字段：unexpected"),
        ({"items": ["查询"], "featureFlags": {"portal": "yes"}}, "功能开关 portal 必须是布尔值"),
        ({"items": ["查询"], "featureFlags": {"unknown": True}}, "不支持的功能开关：unknown"),
    ],
)
def test_validate_platform_config_rejects_invalid_payloads(value, message):
    _, errors = validate_platform_config(value)

    assert message in errors


@pytest.mark.asyncio
async def test_save_platform_config_draft_creates_next_version():
    session = session_with(None, 3)

    draft = await save_platform_config_draft(
        session,
        payload=valid_payload(items=["  船期查询  "]),
        actor_account_id="account-1",
    )

    assert draft.Version == 4
    assert draft.Status == "draft"
    assert draft.Payload["items"] == ["船期查询"]
    assert draft.CreatedByAccountId == "account-1"
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_platform_config_draft_updates_existing_draft():
    existing = PlatformConfigVersion(
        Version=4,
        Status="draft",
        Payload=valid_payload(items=["旧能力"]),
        ValidationErrors=["旧错误"],
    )
    session = session_with(existing)

    draft = await save_platform_config_draft(
        session,
        payload=valid_payload(items=["新能力"]),
        actor_account_id="account-2",
    )

    assert draft is existing
    assert existing.Payload["items"] == ["新能力"]
    assert existing.ValidationErrors == []
    assert existing.CreatedByAccountId == "account-2"


@pytest.mark.asyncio
async def test_save_platform_config_draft_rejects_invalid_payload_before_database_write():
    session = session_with()

    with pytest.raises(PlatformBadRequest, match="配置校验失败"):
        await save_platform_config_draft(session, payload={"items": []}, actor_account_id="account-1")

    session.execute.assert_not_awaited()
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_publish_platform_config_rolls_previous_publish_into_history():
    draft = PlatformConfigVersion(Version=2, Status="draft", Payload=valid_payload())
    current = PlatformConfigVersion(Version=1, Status="published", Payload=valid_payload())
    session = session_with(draft, current)

    published = await publish_platform_config(session, actor_account_id="account-1")

    assert published is draft
    assert draft.Status == "published"
    assert draft.PublishedByAccountId == "account-1"
    assert current.Status == "rolled_back"
    assert current.RollbackSourceVersion == 2
    assert current.RolledBackByAccountId == "account-1"
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_platform_config_rejects_invalid_draft():
    draft = PlatformConfigVersion(
        Version=2,
        Status="draft",
        Payload=valid_payload(),
        ValidationErrors=["能力列表无效"],
    )
    session = session_with(draft)

    with pytest.raises(PlatformBadRequest, match="配置草稿未通过校验"):
        await publish_platform_config(session, actor_account_id="account-1")

    session.execute.assert_awaited_once()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_rollback_platform_config_publishes_target_and_preserves_current_history():
    target = PlatformConfigVersion(Version=1, Status="rolled_back", Payload=valid_payload(items=["旧能力"]))
    current = PlatformConfigVersion(Version=2, Status="published", Payload=valid_payload(items=["新能力"]))
    session = session_with(target, current)

    result = await rollback_platform_config(session, version=1, actor_account_id="account-3")

    assert result is target
    assert target.Status == "published"
    assert target.PublishedByAccountId == "account-3"
    assert current.Status == "rolled_back"
    assert current.RollbackSourceVersion == 1
    assert current.RolledBackByAccountId == "account-3"


@pytest.mark.asyncio
async def test_rollback_platform_config_rejects_draft_target():
    draft = PlatformConfigVersion(Version=3, Status="draft", Payload=valid_payload())
    session = session_with(draft)

    with pytest.raises(PlatformNotFound, match="草稿"):
        await rollback_platform_config(session, version=3, actor_account_id="account-1")

    session.execute.assert_awaited_once()


def test_require_permission_rejects_non_admin_context():
    context = SimpleNamespace(permissions=permissions_for_role(PlatformRole.CUSTOMER))

    with pytest.raises(PlatformForbidden, match="没有执行此操作的权限"):
        require_permission(context, "platform.manage")


@pytest.mark.asyncio
async def test_update_user_access_reconciles_memberships_role_and_contexts(monkeypatch):
    user, account = platform_user_and_account()
    retained_id = str(uuid.uuid4())
    removed_id = str(uuid.uuid4())
    added_id = str(uuid.uuid4())
    retained = PlatformMembership(
        UserId=user.Id,
        EnterpriseId=retained_id,
        MembershipRole=PlatformRole.CUSTOMER,
        Active=True,
    )
    removed = PlatformMembership(
        UserId=user.Id,
        EnterpriseId=removed_id,
        MembershipRole=PlatformRole.CUSTOMER,
        Active=True,
    )
    retained_enterprise = PlatformEnterprise(
        Id=retained_id,
        Name="保留企业",
        CustomerCode="M3-RETAINED",
        Status=EnterpriseStatus.ACTIVE,
    )
    added_enterprise = PlatformEnterprise(
        Id=added_id,
        Name="新增企业",
        CustomerCode="M3-ADDED",
        Status=EnterpriseStatus.ACTIVE,
    )
    session = session_with(
        user,
        account,
        [retained, removed],
        [retained_enterprise, added_enterprise],
    )
    revoke = AsyncMock()
    monkeypatch.setattr("core.platform.revoke_account_execution_contexts", revoke)

    updated, active_memberships = await update_platform_user_access(
        session,
        user_id=str(user.Id),
        role=PlatformRole.STAFF,
        enterprise_ids=[retained_id, added_id],
    )

    assert updated is user
    assert user.Role == PlatformRole.STAFF
    assert account.Role == AccountRole.NORMAL
    assert retained.Active is True
    assert retained.MembershipRole == PlatformRole.STAFF
    assert removed.Active is False
    assert active_memberships == [retained]
    added_membership = next(
        call.args[0]
        for call in session.add.call_args_list
        if isinstance(call.args[0], PlatformMembership)
        and str(call.args[0].EnterpriseId) == added_id
    )
    assert added_membership.Active is True
    assert added_membership.MembershipRole == PlatformRole.STAFF
    revoke.assert_awaited_once_with(session, str(account.Id))
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_user_access_reactivates_selected_membership(monkeypatch):
    user, account = platform_user_and_account(role=PlatformRole.STAFF)
    enterprise_id = str(uuid.uuid4())
    membership = PlatformMembership(
        UserId=user.Id,
        EnterpriseId=enterprise_id,
        MembershipRole=PlatformRole.CUSTOMER,
        Active=False,
    )
    enterprise = PlatformEnterprise(
        Id=enterprise_id,
        Name="重新授权企业",
        CustomerCode="M3-REACTIVATE",
        Status=EnterpriseStatus.ACTIVE,
    )
    session = session_with(user, account, [membership], [enterprise])
    monkeypatch.setattr("core.platform.revoke_account_execution_contexts", AsyncMock())

    await update_platform_user_access(
        session,
        user_id=str(user.Id),
        enterprise_ids=[enterprise_id],
    )

    assert membership.Active is True
    assert membership.MembershipRole == PlatformRole.STAFF
    created_memberships = [
        call.args[0]
        for call in session.add.call_args_list
        if isinstance(call.args[0], PlatformMembership) and call.args[0] is not membership
    ]
    assert created_memberships == []


@pytest.mark.asyncio
async def test_update_user_access_syncs_admin_account_role(monkeypatch):
    user, account = platform_user_and_account(role=PlatformRole.STAFF)
    session = session_with(user, account, [])
    monkeypatch.setattr("core.platform.revoke_account_execution_contexts", AsyncMock())

    await update_platform_user_access(
        session,
        user_id=str(user.Id),
        role=PlatformRole.ADMIN,
    )

    assert user.Role == PlatformRole.ADMIN
    assert account.Role == AccountRole.ADMIN


@pytest.mark.asyncio
async def test_update_user_access_rejects_customer_without_enterprise(monkeypatch):
    user, account = platform_user_and_account()
    session = session_with(user, account, [], [])
    revoke = AsyncMock()
    monkeypatch.setattr("core.platform.revoke_account_execution_contexts", revoke)

    with pytest.raises(PlatformBadRequest, match="至少一家企业"):
        await update_platform_user_access(
            session,
            user_id=str(user.Id),
            enterprise_ids=[],
        )

    revoke.assert_not_awaited()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_user_access_rejects_invalid_or_duplicate_enterprise_ids():
    user, account = platform_user_and_account(role=PlatformRole.STAFF)
    invalid_session = session_with(user, account, [])
    with pytest.raises(PlatformBadRequest, match="企业 ID格式不正确"):
        await update_platform_user_access(
            invalid_session,
            user_id=str(user.Id),
            enterprise_ids=["not-a-uuid"],
        )

    enterprise_id = str(uuid.uuid4())
    duplicate_session = session_with(user, account, [])
    with pytest.raises(PlatformBadRequest, match="不能包含重复项"):
        await update_platform_user_access(
            duplicate_session,
            user_id=str(user.Id),
            enterprise_ids=[enterprise_id, enterprise_id],
        )


@pytest.mark.asyncio
async def test_update_user_access_rejects_missing_or_suspended_enterprises():
    user, account = platform_user_and_account(role=PlatformRole.STAFF)
    enterprise_id = str(uuid.uuid4())
    missing_session = session_with(user, account, [], [])
    with pytest.raises(PlatformBadRequest, match="企业不存在"):
        await update_platform_user_access(
            missing_session,
            user_id=str(user.Id),
            enterprise_ids=[enterprise_id],
        )

    suspended = PlatformEnterprise(
        Id=enterprise_id,
        Name="已停用企业",
        CustomerCode="M3-SUSPENDED",
        Status=EnterpriseStatus.SUSPENDED,
    )
    suspended_session = session_with(user, account, [], [suspended])
    with pytest.raises(PlatformBadRequest, match="不能绑定已停用企业"):
        await update_platform_user_access(
            suspended_session,
            user_id=str(user.Id),
            enterprise_ids=[enterprise_id],
        )


@pytest.mark.asyncio
async def test_update_user_access_rejects_invalid_user_uuid_before_database_access():
    session = session_with()

    with pytest.raises(PlatformBadRequest, match="用户 ID格式不正确"):
        await update_platform_user_access(
            session,
            user_id="not-a-uuid",
            role=PlatformRole.ADMIN,
        )

    session.execute.assert_not_awaited()


def execution_context_fixtures(*, expires_at=None, revoked_at=None, permission_version=None):
    user, account = platform_user_and_account(role=PlatformRole.CUSTOMER)
    account.Status = "active"
    enterprise = PlatformEnterprise(
        Id=str(uuid.uuid4()),
        Name="上下文企业",
        CustomerCode="M3-CONTEXT",
        Status=EnterpriseStatus.ACTIVE,
    )
    membership = PlatformMembership(
        Id=str(uuid.uuid4()),
        UserId=user.Id,
        EnterpriseId=enterprise.Id,
        MembershipRole=PlatformRole.CUSTOMER,
        Active=True,
    )
    auth_session = PlatformAuthSession(
        Id=str(uuid.uuid4()),
        AccountId=account.Id,
        TokenId="platform-session-token",
        ExpiresAt=utc_now() + timedelta(hours=1),
        RevokedAt=None,
    )
    token = "pct_" + ("x" * 48)
    context = PlatformExecutionContext(
        Id=str(uuid.uuid4()),
        TokenHash=execution_token_hash(token),
        UserId=user.Id,
        AccountId=account.Id,
        EnterpriseId=enterprise.Id,
        PlatformSessionId=auth_session.Id,
        AgentId="agent-1",
        Channel="web",
        RunId="run-1",
        PermissionVersion=permission_version or "user-role:customer|membership-role:customer",
        ExpiresAt=expires_at or (utc_now() + timedelta(minutes=5)),
        RevokedAt=revoked_at,
    )
    definition = PlatformToolDefinition(
        Id=str(uuid.uuid4()),
        Name="shipment.lookup",
        Version="1.0",
        Permission="shipment.read",
        Enabled=True,
        ReadOnly=True,
    )
    return token, context, user, account, enterprise, auth_session, membership, definition


@pytest.mark.asyncio
async def test_load_execution_context_rejects_expired_context_before_identity_lookup():
    token, context, *_ = execution_context_fixtures(expires_at=utc_now() - timedelta(seconds=1))
    session = session_with(context)

    with pytest.raises(AccountUnauthorized, match="执行上下文已失效"):
        await load_execution_context(
            session,
            token=token,
            tool_name="shipment.lookup",
            request_id="request-expired",
        )

    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_load_execution_context_rejects_revoked_context_before_identity_lookup():
    token, context, *_ = execution_context_fixtures(revoked_at=utc_now() - timedelta(seconds=1))
    session = session_with(context)

    with pytest.raises(AccountUnauthorized, match="执行上下文已失效"):
        await load_execution_context(
            session,
            token=token,
            tool_name="shipment.lookup",
            request_id="request-revoked",
        )

    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_load_execution_context_rejects_permission_narrowing_after_issue():
    token, context, user, account, enterprise, auth_session, membership, definition = execution_context_fixtures(
        permission_version="user-role:customer|membership-role:staff",
    )
    session = session_with(
        context,
        user,
        account,
        enterprise,
        auth_session,
        membership,
        definition,
        None,
    )

    with pytest.raises(AccountUnauthorized, match="执行上下文已失效"):
        await load_execution_context(
            session,
            token=token,
            tool_name="shipment.lookup",
            request_id="request-narrowed",
        )

    assert session.execute.await_count == 6


@pytest.mark.asyncio
async def test_load_execution_context_rejects_replayed_tool_request():
    token, context, user, account, enterprise, auth_session, membership, definition = execution_context_fixtures()
    previous_call = SimpleNamespace(Id=str(uuid.uuid4()))
    session = session_with(
        context,
        user,
        account,
        enterprise,
        auth_session,
        membership,
        definition,
        previous_call,
    )

    with pytest.raises(PlatformForbidden, match="工具请求已处理"):
        await load_execution_context(
            session,
            token=token,
            tool_name="shipment.lookup",
            request_id="request-replayed",
        )

    assert session.execute.await_count == 8
