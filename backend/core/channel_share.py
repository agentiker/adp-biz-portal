"""No-login, read-only share links for a single channel query result.

A channel reply too long for a chat bubble links to a rendered result page that
must open without a portal login. Access is therefore a high-entropy bearer
token; only its SHA-256 digest is stored, so a database read cannot recover a
working link. Each token is scoped to one execution run, expires, and is
revoked when the owning account is disabled or its channel identity is unbound.
This intentionally grants read access to exactly one result — never a portal
session, never other conversations.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.platform import utc_now
from model.platform import PlatformSharedResult


SHARED_RESULT_TOKEN_PREFIX = "psr_"
# None means the link never expires (the card lives in the chat forever, so
# access is bounded by revocation). A positive value opts into a fixed window.
SHARED_RESULT_TTL_SECONDS: int | None = None
MIN_SHARED_RESULT_TTL_SECONDS = 60


def generate_shared_result_token() -> str:
    """Return a fresh, high-entropy share token shown to the client only once."""
    return f"{SHARED_RESULT_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def shared_result_token_hash(token: str) -> str:
    if not isinstance(token, str) or not token.strip() or len(token.strip()) > 256:
        raise ValueError("shared result token is invalid")
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


async def create_shared_result(
    db: AsyncSession,
    *,
    execution_run_id: str,
    conversation_id: str | None,
    account_id: str,
    enterprise_id: str | None,
    channel: str,
    channel_instance_id: str,
    ttl_seconds: int | None = SHARED_RESULT_TTL_SECONDS,
) -> str:
    """Mint a share link and return the raw token (only its digest is stored).

    ``ttl_seconds`` None (the default) makes the link permanent; a positive
    value bounds it to a fixed window.
    """
    token = generate_shared_result_token()
    expires_at = None
    if ttl_seconds is not None and ttl_seconds > 0:
        expires_at = utc_now() + timedelta(seconds=max(MIN_SHARED_RESULT_TTL_SECONDS, int(ttl_seconds)))
    db.add(
        PlatformSharedResult(
            TokenHash=shared_result_token_hash(token),
            ExecutionRunId=execution_run_id,
            ConversationId=conversation_id,
            AccountId=account_id,
            EnterpriseId=enterprise_id,
            Channel=str(channel)[:48],
            ChannelInstanceId=str(channel_instance_id)[:128],
            ExpiresAt=expires_at,
        )
    )
    return token


async def load_shared_result(db: AsyncSession, token: str) -> PlatformSharedResult | None:
    """Return the live share row for a token, else None (missing/expired/revoked)."""
    try:
        digest = shared_result_token_hash(token)
    except ValueError:
        return None
    row = (
        await db.execute(select(PlatformSharedResult).where(PlatformSharedResult.TokenHash == digest))
    ).scalar_one_or_none()
    if row is None or row.RevokedAt is not None:
        return None
    if row.ExpiresAt is not None and row.ExpiresAt <= utc_now():
        return None
    row.LastAccessedAt = utc_now()
    db.add(row)
    return row


async def revoke_account_shared_results(db: AsyncSession, account_id: str) -> None:
    """Revoke every live share link owned by an account (unbind / disable)."""
    await db.execute(
        update(PlatformSharedResult)
        .where(
            PlatformSharedResult.AccountId == account_id,
            PlatformSharedResult.RevokedAt.is_(None),
        )
        .values(RevokedAt=utc_now())
    )
