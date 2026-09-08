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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.error.account import AccountUnauthorized
from core.error.platform import PlatformBadRequest, PlatformForbidden, PlatformNotFound
from core.platform import utc_now
from model.account import Account, AccountStatus
from model.platform import (
    PlatformChannelIdentity,
    PlatformChannelIdentityStatus,
    PlatformStatus,
    PlatformUser,
)


CHANNEL_IDENTITY_STATE_TTL_SECONDS = 10 * 60
CHANNEL_IDENTITY_STATE_PREFIX = "pci_"


def looks_like_channel_identity_state(value: Any) -> bool:
    """Report whether text is shaped like a binding state.

    The channel callback uses this to divert a binding code into the dedicated
    confirmation flow before the message reaches the agent, so a one-time
    secret is never forwarded to ADP or stored as chat content.
    """
    if not isinstance(value, str):
        return False
    normalized = value.strip()
    return (
        normalized.startswith(CHANNEL_IDENTITY_STATE_PREFIX)
        and 16 < len(normalized) <= 256
        and " " not in normalized
    )


def _identity_text(value: Any, *, field: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise PlatformBadRequest(f"{field}格式不正确")
    normalized = value.strip()
    if not normalized or len(normalized) > max_length:
        raise PlatformBadRequest(f"{field}格式不正确")
    return normalized


def generate_channel_identity_state() -> str:
    """Generate a high-entropy, one-time state returned only to the browser."""
    return f"{CHANNEL_IDENTITY_STATE_PREFIX}{secrets.token_urlsafe(32)}"


async def _active_identity_exists(
    db: AsyncSession,
    *,
    channel: str,
    channel_instance_id: str,
    external_identity_id: str,
    exclude_id: str | None = None,
) -> bool:
    """Report whether an active binding already owns this external identity.

    Two rows are fetched so a pre-existing duplicate is reported instead of
    raising, which keeps the caller able to fail closed with a clear message.
    """
    statement = select(PlatformChannelIdentity.Id).where(
        PlatformChannelIdentity.Channel == channel,
        PlatformChannelIdentity.ChannelInstanceId == channel_instance_id,
        PlatformChannelIdentity.ExternalIdentityId == external_identity_id,
        PlatformChannelIdentity.Status == PlatformChannelIdentityStatus.ACTIVE,
    )
    if exclude_id is not None:
        statement = statement.where(PlatformChannelIdentity.Id != exclude_id)
    rows = list((await db.execute(statement.limit(2))).scalars().all())
    return bool(rows)


def channel_identity_state_hash(state: str) -> str:
    normalized = _identity_text(state, field="绑定状态", max_length=256)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def external_identity_fingerprint(external_identity_id: str | None) -> str:
    """Return a non-sensitive audit label for an external identity."""
    if external_identity_id is None:
        # A binding awaiting channel confirmation has no identity to label yet.
        return "pending"
    normalized = _identity_text(external_identity_id, field="渠道身份", max_length=255)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def serialize_channel_identity(row: PlatformChannelIdentity) -> dict[str, Any]:
    return {
        "id": str(row.Id),
        "userId": str(row.UserId),
        "accountId": str(row.AccountId),
        "enterpriseId": str(row.EnterpriseId) if row.EnterpriseId else None,
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
    channel: str,
    channel_instance_id: str,
    external_identity_id: str | None = None,
) -> tuple[PlatformChannelIdentity, str]:
    """Create a pending platform-user binding.

    ``external_identity_id`` is optional because the browser usually cannot
    learn it: a customer does not know their own WeChat OpenID. When it is
    omitted the binding is completed by the trusted channel adapter, which
    reports the real sender of the message carrying this state. When the page
    does know the identity (for example after channel web authorization) it is
    recorded up front and confirmation must match it exactly.

    Enterprise membership is intentionally not checked here. A channel
    identity identifies the platform user; the worker resolves the business
    enterprise dynamically when a message is executed.
    """
    channel = _identity_text(channel, field="渠道", max_length=48)
    channel_instance_id = _identity_text(channel_instance_id, field="渠道实例", max_length=128)
    if external_identity_id is not None:
        external_identity_id = _identity_text(external_identity_id, field="渠道身份", max_length=255)

    user = (
        await db.execute(select(PlatformUser).where(PlatformUser.Id == user_id))
    ).scalar_one_or_none()
    account = (await db.execute(select(Account).where(Account.Id == account_id))).scalar_one_or_none()
    if (
        user is None
        or account is None
        or str(user.AccountId) != str(account_id)
        or user.Status != PlatformStatus.ACTIVE
        or account.Status in {AccountStatus.BANNED, AccountStatus.PENDING}
    ):
        raise PlatformForbidden("当前账号不可绑定渠道身份")

    if external_identity_id is not None and await _active_identity_exists(
        db,
        channel=channel,
        channel_instance_id=channel_instance_id,
        external_identity_id=external_identity_id,
    ):
        raise PlatformBadRequest("该渠道身份已经绑定")

    state = generate_channel_identity_state()
    now = utc_now()
    row = PlatformChannelIdentity(
        UserId=user_id,
        AccountId=account_id,
        EnterpriseId=None,
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


def _close_pending(
    db: AsyncSession,
    row: PlatformChannelIdentity,
    *,
    status: str,
    now: Any,
) -> None:
    """Terminate a pending binding and burn its one-time state."""
    row.Status = status
    if status == PlatformChannelIdentityStatus.REVOKED:
        row.RevokedAt = now
    row.StateHash = None
    row.UpdatedAt = now
    db.add(row)


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
        _close_pending(db, row, status=PlatformChannelIdentityStatus.EXPIRED, now=now)
        await db.flush()
        raise PlatformBadRequest("绑定状态已过期")
    if row.ExternalIdentityId is not None and row.ExternalIdentityId != external_identity_id:
        # Do not allow a valid state to be transferred to another sender.
        _close_pending(db, row, status=PlatformChannelIdentityStatus.REVOKED, now=now)
        await db.flush()
        raise PlatformForbidden("渠道身份与绑定状态不匹配")

    if await _active_identity_exists(
        db,
        channel=channel,
        channel_instance_id=channel_instance_id,
        external_identity_id=external_identity_id,
        exclude_id=row.Id,
    ):
        _close_pending(db, row, status=PlatformChannelIdentityStatus.REVOKED, now=now)
        await db.flush()
        raise PlatformBadRequest("该渠道身份已经绑定")

    user = (await db.execute(select(PlatformUser).where(PlatformUser.Id == row.UserId))).scalar_one_or_none()
    account = (await db.execute(select(Account).where(Account.Id == row.AccountId))).scalar_one_or_none()
    if (
        user is None
        or account is None
        or str(user.AccountId) != str(row.AccountId)
        or user.Status != PlatformStatus.ACTIVE
        or account.Status in {AccountStatus.BANNED, AccountStatus.PENDING}
    ):
        _close_pending(db, row, status=PlatformChannelIdentityStatus.REVOKED, now=now)
        await db.flush()
        raise AccountUnauthorized("绑定账号已失效")

    # The trusted adapter is the authority on who actually sent the message, so
    # a binding started without a known identity adopts it here.
    row.ExternalIdentityId = external_identity_id
    row.Status = PlatformChannelIdentityStatus.ACTIVE
    row.ConfirmedAt = now
    row.StateExpiresAt = None
    row.StateHash = None
    row.UpdatedAt = now
    db.add(row)
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError as exc:
        # The partial unique index rejected a concurrent confirmation for the
        # same external identity. Fail closed rather than leaving two owners.
        raise PlatformBadRequest("该渠道身份已经绑定") from exc
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


async def resolve_active_channel_identity(
    db: AsyncSession,
    *,
    channel: str,
    channel_instance_id: str,
    external_identity_id: str,
) -> PlatformChannelIdentity | None:
    """Resolve a sender only through an active, server-confirmed binding.

    Two rows are read so a legacy duplicate (created before the database
    enforced uniqueness) resolves to nobody instead of raising and taking the
    whole channel down.
    """
    rows = list(
        (
            await db.execute(
                select(PlatformChannelIdentity)
                .where(
                    PlatformChannelIdentity.Channel == _identity_text(channel, field="渠道", max_length=48),
                    PlatformChannelIdentity.ChannelInstanceId == _identity_text(channel_instance_id, field="渠道实例", max_length=128),
                    PlatformChannelIdentity.ExternalIdentityId == _identity_text(external_identity_id, field="渠道身份", max_length=255),
                    PlatformChannelIdentity.Status == PlatformChannelIdentityStatus.ACTIVE,
                )
                .limit(2)
            )
        ).scalars().all()
    )
    if len(rows) != 1:
        return None
    row = rows[0]
    user = (await db.execute(select(PlatformUser).where(PlatformUser.Id == row.UserId))).scalar_one_or_none()
    account = (await db.execute(select(Account).where(Account.Id == row.AccountId))).scalar_one_or_none()
    if (
        user is None
        or account is None
        or str(user.AccountId) != str(row.AccountId)
        or user.Status != PlatformStatus.ACTIVE
        or account.Status in {AccountStatus.BANNED, AccountStatus.PENDING}
    ):
        return None
    return row
