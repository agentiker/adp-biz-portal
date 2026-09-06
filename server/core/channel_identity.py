"""Channel identity binding lifecycle.

Binding is deliberately a two-party flow: the logged-in platform user starts
the request, while a trusted channel adapter confirms the exact external
identity. Message text is never used as an identity assertion.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.error.account import AccountUnauthorized
from core.error.platform import PlatformBadRequest, PlatformForbidden, PlatformNotFound
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


CHANNEL_IDENTITY_STATE_TTL_SECONDS = 10 * 60


def _identity_text(value: Any, *, field: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise PlatformBadRequest(f"{field}格式不正确")
    normalized = value.strip()
    if not normalized or len(normalized) > max_length:
        raise PlatformBadRequest(f"{field}格式不正确")
    return normalized


def generate_channel_identity_state() -> str:
    """Generate a high-entropy, one-time state returned only to the browser."""
    return f"pci_{secrets.token_urlsafe(32)}"


def channel_identity_state_hash(state: str) -> str:
    normalized = _identity_text(state, field="绑定状态", max_length=256)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def external_identity_fingerprint(external_identity_id: str) -> str:
    """Return a non-sensitive audit label for an external identity."""
    normalized = _identity_text(external_identity_id, field="渠道身份", max_length=255)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def serialize_channel_identity(row: PlatformChannelIdentity) -> dict[str, Any]:
    return {
        "id": str(row.Id),
        "userId": str(row.UserId),
        "accountId": str(row.AccountId),
        "enterpriseId": str(row.EnterpriseId),
        "channel": row.Channel,
        "channelInstanceId": row.ChannelInstanceId,
        "externalIdentityId": row.ExternalIdentityId,
        "status": row.Status,
        "stateExpiresAt": row.StateExpiresAt.isoformat() if row.StateExpiresAt else None,
        "confirmedAt": row.ConfirmedAt.isoformat() if row.ConfirmedAt else None,
        "revokedAt": row.RevokedAt.isoformat() if row.RevokedAt else None,
        "createdAt": row.CreatedAt.isoformat() if row.CreatedAt else "",
        "updatedAt": row.UpdatedAt.isoformat() if row.UpdatedAt else "",
    }


async def begin_channel_identity_binding(
    db: AsyncSession,
    *,
    user_id: str,
    account_id: str,
    enterprise_id: str,
    channel: str,
    channel_instance_id: str,
    external_identity_id: str,
) -> tuple[PlatformChannelIdentity, str]:
    """Create a pending binding after checking the user's active scope."""
    channel = _identity_text(channel, field="渠道", max_length=48)
    channel_instance_id = _identity_text(channel_instance_id, field="渠道实例", max_length=128)
    external_identity_id = _identity_text(external_identity_id, field="渠道身份", max_length=255)

    user = (
        await db.execute(select(PlatformUser).where(PlatformUser.Id == user_id))
    ).scalar_one_or_none()
    account = (await db.execute(select(Account).where(Account.Id == account_id))).scalar_one_or_none()
    enterprise = (
        await db.execute(select(PlatformEnterprise).where(PlatformEnterprise.Id == enterprise_id))
    ).scalar_one_or_none()
    membership = (
        await db.execute(
            select(PlatformMembership).where(
                PlatformMembership.UserId == user_id,
                PlatformMembership.EnterpriseId == enterprise_id,
                PlatformMembership.Active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if (
        user is None
        or account is None
        or enterprise is None
        or membership is None
        or str(user.AccountId) != str(account_id)
        or user.Status != PlatformStatus.ACTIVE
        or account.Status in {AccountStatus.BANNED, AccountStatus.PENDING}
        or enterprise.Status != EnterpriseStatus.ACTIVE
    ):
        raise PlatformForbidden("当前账号没有可绑定的企业范围")

    existing = (
        await db.execute(
            select(PlatformChannelIdentity).where(
                PlatformChannelIdentity.Channel == channel,
                PlatformChannelIdentity.ChannelInstanceId == channel_instance_id,
                PlatformChannelIdentity.ExternalIdentityId == external_identity_id,
                PlatformChannelIdentity.Status == PlatformChannelIdentityStatus.ACTIVE,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise PlatformBadRequest("该渠道身份已经绑定")

    state = generate_channel_identity_state()
    now = utc_now()
    row = PlatformChannelIdentity(
        UserId=user_id,
        AccountId=account_id,
        EnterpriseId=enterprise_id,
        Channel=channel,
        ChannelInstanceId=channel_instance_id,
        ExternalIdentityId=external_identity_id,
        Status=PlatformChannelIdentityStatus.PENDING,
        StateHash=channel_identity_state_hash(state),
        StateExpiresAt=now + timedelta(seconds=CHANNEL_IDENTITY_STATE_TTL_SECONDS),
    )
    db.add(row)
    await db.flush()
    return row, state


async def confirm_channel_identity_binding(
    db: AsyncSession,
    *,
    state: str,
    channel: str,
    channel_instance_id: str,
    external_identity_id: str,
) -> PlatformChannelIdentity:
    """Confirm one pending state against the exact channel sender identity."""
    channel = _identity_text(channel, field="渠道", max_length=48)
    channel_instance_id = _identity_text(channel_instance_id, field="渠道实例", max_length=128)
    external_identity_id = _identity_text(external_identity_id, field="渠道身份", max_length=255)
    row = (
        await db.execute(
            select(PlatformChannelIdentity).where(
                PlatformChannelIdentity.StateHash == channel_identity_state_hash(state),
                PlatformChannelIdentity.Channel == channel,
                PlatformChannelIdentity.ChannelInstanceId == channel_instance_id,
                PlatformChannelIdentity.Status == PlatformChannelIdentityStatus.PENDING,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise PlatformBadRequest("绑定状态无效、已使用或已失效")

    now = utc_now()
    if row.StateExpiresAt is None or row.StateExpiresAt <= now:
        row.Status = PlatformChannelIdentityStatus.EXPIRED
        row.StateHash = None
        row.UpdatedAt = now
        db.add(row)
        await db.flush()
        raise PlatformBadRequest("绑定状态已过期")
    if row.ExternalIdentityId != external_identity_id:
        # Do not allow a valid state to be transferred to another sender.
        row.Status = PlatformChannelIdentityStatus.REVOKED
        row.RevokedAt = now
        row.StateHash = None
        row.UpdatedAt = now
        db.add(row)
        await db.flush()
        raise PlatformForbidden("渠道身份与绑定状态不匹配")

    duplicate = (
        await db.execute(
            select(PlatformChannelIdentity).where(
                PlatformChannelIdentity.Channel == channel,
                PlatformChannelIdentity.ChannelInstanceId == channel_instance_id,
                PlatformChannelIdentity.ExternalIdentityId == external_identity_id,
                PlatformChannelIdentity.Status == PlatformChannelIdentityStatus.ACTIVE,
                PlatformChannelIdentity.Id != row.Id,
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        row.Status = PlatformChannelIdentityStatus.REVOKED
        row.RevokedAt = now
        row.StateHash = None
        row.UpdatedAt = now
        db.add(row)
        await db.flush()
        raise PlatformBadRequest("该渠道身份已经绑定")

    user = (await db.execute(select(PlatformUser).where(PlatformUser.Id == row.UserId))).scalar_one_or_none()
    account = (await db.execute(select(Account).where(Account.Id == row.AccountId))).scalar_one_or_none()
    enterprise = (await db.execute(select(PlatformEnterprise).where(PlatformEnterprise.Id == row.EnterpriseId))).scalar_one_or_none()
    membership = (
        await db.execute(
            select(PlatformMembership).where(
                PlatformMembership.UserId == row.UserId,
                PlatformMembership.EnterpriseId == row.EnterpriseId,
                PlatformMembership.Active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if (
        user is None
        or account is None
        or enterprise is None
        or membership is None
        or user.Status != PlatformStatus.ACTIVE
        or account.Status in {AccountStatus.BANNED, AccountStatus.PENDING}
        or enterprise.Status != EnterpriseStatus.ACTIVE
    ):
        row.Status = PlatformChannelIdentityStatus.REVOKED
        row.RevokedAt = now
        row.StateHash = None
        row.UpdatedAt = now
        db.add(row)
        await db.flush()
        raise AccountUnauthorized("绑定账号已失效")

    row.Status = PlatformChannelIdentityStatus.ACTIVE
    row.ConfirmedAt = now
    row.StateExpiresAt = None
    row.StateHash = None
    row.UpdatedAt = now
    db.add(row)
    await db.flush()
    return row


async def revoke_channel_identity(
    db: AsyncSession,
    *,
    identity_id: str,
    account_id: str | None = None,
) -> PlatformChannelIdentity:
    row = await db.get(PlatformChannelIdentity, identity_id)
    if row is None or (account_id is not None and str(row.AccountId) != str(account_id)):
        raise PlatformNotFound("渠道身份不存在或无权访问")
    if row.Status in {PlatformChannelIdentityStatus.ACTIVE, PlatformChannelIdentityStatus.PENDING}:
        row.Status = PlatformChannelIdentityStatus.REVOKED
        row.RevokedAt = utc_now()
        row.StateHash = None
        row.StateExpiresAt = None
        row.UpdatedAt = utc_now()
        db.add(row)
        await db.flush()
    return row


async def revoke_account_channel_identities(db: AsyncSession, account_id: str) -> int:
    rows = list(
        (
            await db.execute(
                select(PlatformChannelIdentity).where(
                    PlatformChannelIdentity.AccountId == account_id,
                    PlatformChannelIdentity.Status.in_((PlatformChannelIdentityStatus.PENDING, PlatformChannelIdentityStatus.ACTIVE)),
                )
            )
        ).scalars().all()
    )
    now = utc_now()
    for row in rows:
        row.Status = PlatformChannelIdentityStatus.REVOKED
        row.RevokedAt = now
        row.StateHash = None
        row.StateExpiresAt = None
        row.UpdatedAt = now
        db.add(row)
    return len(rows)


async def revoke_enterprise_channel_identities(db: AsyncSession, enterprise_id: str) -> int:
    rows = list(
        (
            await db.execute(
                select(PlatformChannelIdentity).where(
                    PlatformChannelIdentity.EnterpriseId == enterprise_id,
                    PlatformChannelIdentity.Status.in_((PlatformChannelIdentityStatus.PENDING, PlatformChannelIdentityStatus.ACTIVE)),
                )
            )
        ).scalars().all()
    )
    now = utc_now()
    for row in rows:
        row.Status = PlatformChannelIdentityStatus.REVOKED
        row.RevokedAt = now
        row.StateHash = None
        row.StateExpiresAt = None
        row.UpdatedAt = now
        db.add(row)
    return len(rows)


async def resolve_active_channel_identity(
    db: AsyncSession,
    *,
    channel: str,
    channel_instance_id: str,
    external_identity_id: str,
) -> PlatformChannelIdentity | None:
    """Resolve a sender only through an active, server-confirmed binding."""
    row = (
        await db.execute(
            select(PlatformChannelIdentity).where(
                PlatformChannelIdentity.Channel == _identity_text(channel, field="渠道", max_length=48),
                PlatformChannelIdentity.ChannelInstanceId == _identity_text(channel_instance_id, field="渠道实例", max_length=128),
                PlatformChannelIdentity.ExternalIdentityId == _identity_text(external_identity_id, field="渠道身份", max_length=255),
                PlatformChannelIdentity.Status == PlatformChannelIdentityStatus.ACTIVE,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    user = (await db.execute(select(PlatformUser).where(PlatformUser.Id == row.UserId))).scalar_one_or_none()
    account = (await db.execute(select(Account).where(Account.Id == row.AccountId))).scalar_one_or_none()
    enterprise = (await db.execute(select(PlatformEnterprise).where(PlatformEnterprise.Id == row.EnterpriseId))).scalar_one_or_none()
    membership = (
        await db.execute(
            select(PlatformMembership).where(
                PlatformMembership.UserId == row.UserId,
                PlatformMembership.EnterpriseId == row.EnterpriseId,
                PlatformMembership.Active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if (
        user is None
        or account is None
        or enterprise is None
        or membership is None
        or user.Status != PlatformStatus.ACTIVE
        or account.Status in {AccountStatus.BANNED, AccountStatus.PENDING}
        or enterprise.Status != EnterpriseStatus.ACTIVE
    ):
        return None
    return row
