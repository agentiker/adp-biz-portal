from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from core.channel_identity import (
    begin_channel_identity_binding,
    channel_identity_state_hash,
    confirm_channel_identity_binding,
    generate_channel_identity_state,
    resolve_active_channel_identity,
)
from core.error.account import AccountUnauthorized
from core.error.platform import PlatformBadRequest, PlatformForbidden
from core.platform import utc_now
from model.account import Account, AccountStatus
from model.platform import (
    EnterpriseStatus,
    PlatformChannelIdentity,
    PlatformChannelIdentityStatus,
    PlatformEnterprise,
    PlatformMembership,
    PlatformStatus,
    PlatformUser,
)


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return self.value


class _FakeDb:
    def __init__(self, *results):
        self.results = list(results)
        self.added = []

    async def execute(self, _statement):
        return _Result(self.results.pop(0))

    async def flush(self):
        return None

    def add(self, value):
        self.added.append(value)


def _active_scope():
    account = Account(Id=uuid4(), Status=AccountStatus.ACTIVE)
    enterprise = PlatformEnterprise(Id=uuid4(), Status=EnterpriseStatus.ACTIVE)
    user = PlatformUser(
        Id=uuid4(),
        AccountId=account.Id,
        Status=PlatformStatus.ACTIVE,
    )
    membership = PlatformMembership(UserId=user.Id, EnterpriseId=enterprise.Id, Active=True)
    return user, account, enterprise, membership


def test_state_is_high_entropy_and_only_digest_is_persisted():
    state = generate_channel_identity_state()
    assert state.startswith("pci_")
    assert len(state) >= 40
    assert channel_identity_state_hash(state) != state
    assert len(channel_identity_state_hash(state)) == 64


@pytest.mark.asyncio
async def test_begin_binding_persists_digest_and_returns_one_time_state():
    user, account, enterprise, membership = _active_scope()
    db = _FakeDb(user, account, enterprise, membership, None)
    row, state = await begin_channel_identity_binding(
        db,
        user_id=str(user.Id),
        account_id=str(account.Id),
        enterprise_id=str(enterprise.Id),
        channel="wecom",
        channel_instance_id="corp-1",
        external_identity_id="user-1",
    )
    assert row.Status == PlatformChannelIdentityStatus.PENDING
    assert row.StateHash == channel_identity_state_hash(state)
    assert state not in row.StateHash
    assert row.StateExpiresAt > utc_now()


@pytest.mark.asyncio
async def test_expired_state_cannot_be_confirmed():
    row = PlatformChannelIdentity(
        Id=uuid4(),
        UserId=uuid4(),
        AccountId=uuid4(),
        EnterpriseId=uuid4(),
        Channel="wecom",
        ChannelInstanceId="corp-1",
        ExternalIdentityId="user-1",
        Status=PlatformChannelIdentityStatus.PENDING,
        StateHash=channel_identity_state_hash("pci_expired"),
        StateExpiresAt=utc_now() - timedelta(seconds=1),
    )
    db = _FakeDb(row)
    with pytest.raises(PlatformBadRequest, match="过期"):
        await confirm_channel_identity_binding(
            db,
            state="pci_expired",
            channel="wecom",
            channel_instance_id="corp-1",
            external_identity_id="user-1",
        )
    assert row.Status == PlatformChannelIdentityStatus.EXPIRED
    assert row.StateHash is None


@pytest.mark.asyncio
async def test_confirmation_is_one_time_and_mismatched_sender_revokes_pending_state():
    user, account, enterprise, membership = _active_scope()
    row = PlatformChannelIdentity(
        Id=uuid4(),
        UserId=user.Id,
        AccountId=account.Id,
        EnterpriseId=enterprise.Id,
        Channel="wecom",
        ChannelInstanceId="corp-1",
        ExternalIdentityId="user-1",
        Status=PlatformChannelIdentityStatus.PENDING,
        StateHash=channel_identity_state_hash("pci_once"),
        StateExpiresAt=utc_now() + timedelta(minutes=5),
    )
    db = _FakeDb(row)
    with pytest.raises(PlatformForbidden, match="不匹配"):
        await confirm_channel_identity_binding(
            db,
            state="pci_once",
            channel="wecom",
            channel_instance_id="corp-1",
            external_identity_id="other-user",
        )
    assert row.Status == PlatformChannelIdentityStatus.REVOKED
    assert row.StateHash is None

    # A revoked/consumed digest can never be confirmed again.
    db = _FakeDb(None)
    with pytest.raises(PlatformBadRequest, match="无效"):
        await confirm_channel_identity_binding(
            db,
            state="pci_once",
            channel="wecom",
            channel_instance_id="corp-1",
            external_identity_id="user-1",
        )


@pytest.mark.asyncio
async def test_successful_confirmation_consumes_state():
    user, account, enterprise, membership = _active_scope()
    row = PlatformChannelIdentity(
        Id=uuid4(),
        UserId=user.Id,
        AccountId=account.Id,
        EnterpriseId=enterprise.Id,
        Channel="wecom",
        ChannelInstanceId="corp-1",
        ExternalIdentityId="user-1",
        Status=PlatformChannelIdentityStatus.PENDING,
        StateHash=channel_identity_state_hash("pci_confirm"),
        StateExpiresAt=utc_now() + timedelta(minutes=5),
    )
    db = _FakeDb(row, None, user, account, enterprise, membership)
    confirmed = await confirm_channel_identity_binding(
        db,
        state="pci_confirm",
        channel="wecom",
        channel_instance_id="corp-1",
        external_identity_id="user-1",
    )
    assert confirmed.Status == PlatformChannelIdentityStatus.ACTIVE
    assert confirmed.StateHash is None
    assert confirmed.StateExpiresAt is None

    with pytest.raises(PlatformBadRequest, match="无效"):
        await confirm_channel_identity_binding(
            _FakeDb(None),
            state="pci_confirm",
            channel="wecom",
            channel_instance_id="corp-1",
            external_identity_id="user-1",
        )


@pytest.mark.asyncio
async def test_confirm_requires_active_user_account_enterprise_and_membership():
    user, account, enterprise, membership = _active_scope()
    row = PlatformChannelIdentity(
        Id=uuid4(),
        UserId=user.Id,
        AccountId=account.Id,
        EnterpriseId=enterprise.Id,
        Channel="wecom",
        ChannelInstanceId="corp-1",
        ExternalIdentityId="user-1",
        Status=PlatformChannelIdentityStatus.PENDING,
        StateHash=channel_identity_state_hash("pci_scope"),
        StateExpiresAt=utc_now() + timedelta(minutes=5),
    )
    account.Status = AccountStatus.BANNED
    db = _FakeDb(row, None, user, account, enterprise, membership)
    with pytest.raises(AccountUnauthorized, match="账号"):
        await confirm_channel_identity_binding(
            db,
            state="pci_scope",
            channel="wecom",
            channel_instance_id="corp-1",
            external_identity_id="user-1",
        )
    assert row.Status == PlatformChannelIdentityStatus.REVOKED


@pytest.mark.asyncio
async def test_resolve_active_identity_returns_none_when_membership_is_revoked():
    user, account, enterprise, _membership = _active_scope()
    row = PlatformChannelIdentity(
        Id=uuid4(),
        UserId=user.Id,
        AccountId=account.Id,
        EnterpriseId=enterprise.Id,
        Channel="wecom",
        ChannelInstanceId="corp-1",
        ExternalIdentityId="user-1",
        Status=PlatformChannelIdentityStatus.ACTIVE,
    )
    db = _FakeDb(row, user, account, enterprise, None)
    assert await resolve_active_channel_identity(
        db,
        channel="wecom",
        channel_instance_id="corp-1",
        external_identity_id="user-1",
    ) is None
