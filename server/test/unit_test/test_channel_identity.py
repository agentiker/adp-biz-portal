from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from core.channel_identity import (
    begin_channel_identity_binding,
    channel_identity_state_hash,
    confirm_channel_identity_binding,
    generate_channel_identity_state,
    resolve_active_channel_identity,
    serialize_channel_identity,
)
from core.error.account import AccountUnauthorized
from core.error.platform import PlatformBadRequest, PlatformForbidden
from core.platform import utc_now
from model.account import Account, AccountStatus
from model.platform import PlatformChannelIdentity, PlatformChannelIdentityStatus, PlatformStatus, PlatformUser


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        if isinstance(self.value, list):
            return self.value[0] if self.value else None
        return self.value

    def scalars(self):
        return self

    def all(self):
        if self.value is None:
            return []
        return list(self.value) if isinstance(self.value, list) else [self.value]


class _NestedTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


class _FakeDb:
    def __init__(self, *results):
        self.results = list(results)
        self.added = []

    async def execute(self, _statement):
        return _Result(self.results.pop(0))

    async def flush(self):
        return None

    def begin_nested(self):
        return _NestedTransaction()

    def add(self, value):
        self.added.append(value)


def _active_user_and_account():
    account = Account(Id=uuid4(), Status=AccountStatus.ACTIVE)
    user = PlatformUser(
        Id=uuid4(),
        AccountId=account.Id,
        Status=PlatformStatus.ACTIVE,
    )
    return user, account


def _write_scope_evidence() -> None:
    output = Path(__file__).resolve().parents[3] / "output" / "tests" / "m3-identity-01-platform-user-scope.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "task": "M3-IDENTITY-01",
                "date": "2026-09-08",
                "scope": "channel identity binds a platform user without enterprise authorization",
                "newBindingEnterpriseId": None,
                "membershipRequiredForBinding": False,
                "membershipRequiredForIdentityResolution": False,
                "accountStateStillValidated": True,
                "enterpriseResolvedBy": "worker at message execution time",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_state_is_high_entropy_and_only_digest_is_persisted():
    state = generate_channel_identity_state()
    assert state.startswith("pci_")
    assert len(state) >= 40
    assert channel_identity_state_hash(state) != state
    assert len(channel_identity_state_hash(state)) == 64


@pytest.mark.asyncio
async def test_begin_binding_persists_digest_and_returns_one_time_state():
    user, account = _active_user_and_account()
    db = _FakeDb(user, account, None)
    row, state = await begin_channel_identity_binding(
        db,
        user_id=str(user.Id),
        account_id=str(account.Id),
        channel="wecom",
        channel_instance_id="corp-1",
        external_identity_id="user-1",
    )
    assert row.Status == PlatformChannelIdentityStatus.PENDING
    assert row.StateHash == channel_identity_state_hash(state)
    assert state not in row.StateHash
    assert row.StateExpiresAt > utc_now()
    assert row.EnterpriseId is None


@pytest.mark.asyncio
async def test_expired_state_cannot_be_confirmed():
    row = PlatformChannelIdentity(
        Id=uuid4(),
        UserId=uuid4(),
        AccountId=uuid4(),
        EnterpriseId=None,
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
    user, account = _active_user_and_account()
    row = PlatformChannelIdentity(
        Id=uuid4(),
        UserId=user.Id,
        AccountId=account.Id,
        EnterpriseId=None,
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
    user, account = _active_user_and_account()
    row = PlatformChannelIdentity(
        Id=uuid4(),
        UserId=user.Id,
        AccountId=account.Id,
        EnterpriseId=None,
        Channel="wecom",
        ChannelInstanceId="corp-1",
        ExternalIdentityId="user-1",
        Status=PlatformChannelIdentityStatus.PENDING,
        StateHash=channel_identity_state_hash("pci_confirm"),
        StateExpiresAt=utc_now() + timedelta(minutes=5),
    )
    db = _FakeDb(row, None, user, account)
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
async def test_confirm_requires_active_user_and_account():
    user, account = _active_user_and_account()
    row = PlatformChannelIdentity(
        Id=uuid4(),
        UserId=user.Id,
        AccountId=account.Id,
        EnterpriseId=None,
        Channel="wecom",
        ChannelInstanceId="corp-1",
        ExternalIdentityId="user-1",
        Status=PlatformChannelIdentityStatus.PENDING,
        StateHash=channel_identity_state_hash("pci_scope"),
        StateExpiresAt=utc_now() + timedelta(minutes=5),
    )
    account.Status = AccountStatus.BANNED
    db = _FakeDb(row, None, user, account)
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
async def test_resolve_active_identity_does_not_require_enterprise_membership():
    user, account = _active_user_and_account()
    row = PlatformChannelIdentity(
        Id=uuid4(),
        UserId=user.Id,
        AccountId=account.Id,
        EnterpriseId=None,
        Channel="wecom",
        ChannelInstanceId="corp-1",
        ExternalIdentityId="user-1",
        Status=PlatformChannelIdentityStatus.ACTIVE,
    )
    db = _FakeDb(row, user, account)
    resolved = await resolve_active_channel_identity(
        db,
        channel="wecom",
        channel_instance_id="corp-1",
        external_identity_id="user-1",
    )
    assert resolved is row
    assert serialize_channel_identity(resolved)["enterpriseId"] is None
    _write_scope_evidence()
