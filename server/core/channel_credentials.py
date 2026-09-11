"""Encrypted storage and tightly scoped access for channel credentials.

The browser-facing admin APIs only use the metadata serializer in this module.
Plaintext decryption is deliberately kept as a separate worker-only helper so
callers have to make the sensitive boundary explicit.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import tagentic_config
from model.platform import PlatformChannelCredential, PlatformChannelCredentialStatus


class ChannelCredentialError(RuntimeError):
    """Base error for credential configuration and decryption failures."""


class ChannelCredentialConfigurationError(ChannelCredentialError):
    """Raised when the deployment has not supplied a valid encryption key."""


class ChannelCredentialUnavailableError(ChannelCredentialError):
    """Raised when a credential cannot be read for the requested scope."""


_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MAX_CREDENTIAL_LENGTH = 64 * 1024
CREDENTIAL_MASK = "********"


@dataclass(frozen=True)
class EncryptedCredential:
    ciphertext: str
    key_version: str
    fingerprint: str


def _validate_version(value: Any) -> str:
    if not isinstance(value, str) or not _VERSION_PATTERN.fullmatch(value.strip()):
        raise ChannelCredentialConfigurationError("channel credential key version is invalid")
    return value.strip()


def _credential_text(value: Any) -> str:
    """Normalize string or structured secrets without ever logging the value."""
    if isinstance(value, str):
        secret = value
    elif isinstance(value, (Mapping, list, tuple)):
        try:
            secret = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise ChannelCredentialError("channel credential is not serializable") from exc
    else:
        raise ChannelCredentialError("channel credential must be a string or JSON object")
    if not secret.strip() or len(secret) > MAX_CREDENTIAL_LENGTH:
        raise ChannelCredentialError("channel credential is empty or too large")
    return secret


def _fernet(key: Any) -> Fernet:
    if not isinstance(key, str) or not key.strip():
        raise ChannelCredentialConfigurationError("channel credential encryption key is not configured")
    try:
        return Fernet(key.strip().encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise ChannelCredentialConfigurationError("channel credential encryption key is invalid") from exc


def _keyring() -> tuple[str, dict[str, Fernet]]:
    current_version = _validate_version(tagentic_config.PLATFORM_CHANNEL_CREDENTIAL_KEY_VERSION)
    keys: dict[str, Fernet] = {current_version: _fernet(tagentic_config.PLATFORM_CHANNEL_CREDENTIAL_KEY)}
    ring = tagentic_config.PLATFORM_CHANNEL_CREDENTIAL_KEY_RING or {}
    if not isinstance(ring, Mapping):
        raise ChannelCredentialConfigurationError("channel credential key ring is invalid")
    for version, key in ring.items():
        normalized_version = _validate_version(version)
        if normalized_version in keys:
            raise ChannelCredentialConfigurationError("channel credential key versions must be unique")
        keys[normalized_version] = _fernet(key)
    return current_version, keys


def encrypt_credential(value: Any) -> EncryptedCredential:
    secret = _credential_text(value)
    key_version, keys = _keyring()
    ciphertext = keys[key_version].encrypt(secret.encode("utf-8")).decode("ascii")
    fingerprint = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    return EncryptedCredential(ciphertext, key_version, fingerprint)


def decrypt_ciphertext(ciphertext: Any, key_version: Any, *, fingerprint: Any = None) -> str:
    """Decrypt a Fernet ciphertext + optional fingerprint check (generic).

    Shared by channel credentials and the ADP-app registry so encrypted secrets
    are never coupled to a single table.
    """
    _, keys = _keyring()
    version = _validate_version(key_version)
    key = keys.get(version)
    if key is None:
        raise ChannelCredentialConfigurationError("channel credential key version is unavailable")
    if not isinstance(ciphertext, str) or not ciphertext:
        raise ChannelCredentialError("channel credential ciphertext is invalid")
    try:
        secret = key.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError) as exc:
        raise ChannelCredentialError("channel credential could not be decrypted") from exc
    if not secret or len(secret) > MAX_CREDENTIAL_LENGTH:
        raise ChannelCredentialError("channel credential plaintext is invalid")
    if fingerprint is not None and hashlib.sha256(secret.encode("utf-8")).hexdigest() != fingerprint:
        raise ChannelCredentialError("channel credential fingerprint does not match")
    return secret


def decrypt_credential(row: PlatformChannelCredential) -> str:
    """Decrypt a row for an internal Worker or channel adapter only."""
    return decrypt_ciphertext(row.Ciphertext, row.KeyVersion, fingerprint=row.Fingerprint)


def serialize_credential(row: PlatformChannelCredential) -> dict[str, Any]:
    """Return metadata only; ciphertext and plaintext are intentionally absent."""
    return {
        "id": str(row.Id),
        "enterpriseId": str(row.EnterpriseId) if row.EnterpriseId else None,
        "connectionId": str(row.ConnectionId) if row.ConnectionId else None,
        "channel": row.Channel,
        "channelInstanceId": row.ChannelInstanceId,
        "credentialMask": CREDENTIAL_MASK,
        "version": int(row.Version or 1),
        "keyVersion": row.KeyVersion,
        "fingerprint": row.Fingerprint,
        "status": row.Status,
        "createdAt": row.CreatedAt.isoformat() if row.CreatedAt else "",
        "updatedAt": row.UpdatedAt.isoformat() if row.UpdatedAt else "",
        "rotatedAt": row.RotatedAt.isoformat() if row.RotatedAt else None,
        "expiresAt": row.ExpiresAt.isoformat() if row.ExpiresAt else None,
    }


async def load_active_credential(
    db: AsyncSession,
    *,
    channel: str,
    channel_instance_id: str,
    enterprise_id: str | None = None,
    connection_id: str | None = None,
) -> str:
    """Load one active platform credential.

    The enterprise and connection arguments are retained for callers compiled
    against the old API, but platform channel credentials are no longer gated
    by either enterprise bindings or ADP connection rows.
    """
    statement = select(PlatformChannelCredential).where(
        PlatformChannelCredential.Channel == channel,
        PlatformChannelCredential.ChannelInstanceId == channel_instance_id,
        PlatformChannelCredential.Status == PlatformChannelCredentialStatus.ACTIVE,
    )
    if enterprise_id:
        statement = statement.where(
            (PlatformChannelCredential.EnterpriseId == enterprise_id)
            | PlatformChannelCredential.EnterpriseId.is_(None)
        )
    if connection_id:
        statement = statement.where(
            (PlatformChannelCredential.ConnectionId == connection_id)
            | PlatformChannelCredential.ConnectionId.is_(None)
        )
    row = (await db.execute(statement)).scalar_one_or_none()
    if row is None:
        raise ChannelCredentialUnavailableError("active channel credential is unavailable")
    return decrypt_credential(row)


async def load_active_channel_instance_credential(
    db: AsyncSession,
    *,
    channel: str,
    channel_instance_id: str,
) -> str:
    """Load the single active credential used by a public callback.

    Public callbacks do not carry an enterprise ID.  The channel instance is
    therefore required to be globally unambiguous; multiple active rows fail
    closed instead of selecting an arbitrary tenant credential.
    """
    rows = list((await db.execute(
        select(PlatformChannelCredential).where(
            PlatformChannelCredential.Channel == channel,
            PlatformChannelCredential.ChannelInstanceId == channel_instance_id,
            PlatformChannelCredential.Status == PlatformChannelCredentialStatus.ACTIVE,
        )
    )).scalars().all())
    if len(rows) != 1:
        raise ChannelCredentialUnavailableError("channel instance credential is unavailable or ambiguous")
    return decrypt_credential(rows[0])


async def list_active_channel_instances(db: AsyncSession, *, channel: str) -> list[str]:
    """Return active instance IDs for one channel without decrypting anything.

    A customer starting a binding must not have to invent an instance ID, and
    the browser has no business holding credential material, so only the
    non-secret instance identifiers are read here.
    """
    rows = (
        await db.execute(
            select(PlatformChannelCredential.ChannelInstanceId)
            .where(
                PlatformChannelCredential.Channel == channel,
                PlatformChannelCredential.Status == PlatformChannelCredentialStatus.ACTIVE,
            )
            .order_by(PlatformChannelCredential.ChannelInstanceId)
        )
    ).scalars().all()
    return [str(item) for item in rows]


async def load_active_channel_credentials(
    db: AsyncSession, *, channel: str
) -> list[tuple[str, str]]:
    """Load all active instance credentials for a fixed public callback.

    The caller must still enforce an unambiguous match; returning instance IDs
    keeps routing decisions explicit and avoids silently selecting a tenant.
    """
    rows = list((await db.execute(
        select(PlatformChannelCredential).where(
            PlatformChannelCredential.Channel == channel,
            PlatformChannelCredential.Status == PlatformChannelCredentialStatus.ACTIVE,
        )
    )).scalars().all())
    return [(str(row.ChannelInstanceId), decrypt_credential(row)) for row in rows]
