"""Connector credentials: random secrets, hash-only storage, no auth cache."""
import hashlib
import secrets
import uuid
from datetime import datetime, UTC

from sqlalchemy import select
from core.error.platform import PlatformBadRequest, PlatformNotFound
from core.platform import AccountUnauthorized
from model.platform import PlatformAdpApiKey


def serialize_api_key(row):
    return {"id": str(row.Id), "name": row.Name, "prefix": row.Prefix,
            "createdAt": row.CreatedAt.isoformat(),
            "revokedAt": row.RevokedAt.isoformat() if row.RevokedAt else None}


async def create_api_key(db, name):
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 128:
        raise PlatformBadRequest("名称必须为 1–128 个字符")
    secret = "adp_" + secrets.token_urlsafe(32)
    row = PlatformAdpApiKey(Name=name.strip(), Prefix=secret[:12],
                            KeyHash=hashlib.sha256(secret.encode()).hexdigest())
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row, secret


async def list_api_keys(db):
    return (await db.execute(select(PlatformAdpApiKey).order_by(PlatformAdpApiKey.CreatedAt.desc()))).scalars().all()


async def revoke_api_key(db, key_id):
    try:
        parsed = uuid.UUID(key_id)
    except (ValueError, TypeError, AttributeError):
        raise PlatformBadRequest("API Key ID 格式无效")
    row = await db.get(PlatformAdpApiKey, parsed)
    if row is None:
        raise PlatformNotFound("API Key 不存在")
    if row.RevokedAt is None:
        row.RevokedAt = datetime.now(UTC).replace(tzinfo=None)
    await db.flush()
    return row


async def require_connector_key(db, provided):
    if not isinstance(provided, str) or len(provided) != 47 or not provided.startswith("adp_"):
        raise AccountUnauthorized("连接器 API Key 无效")
    key_id = (await db.execute(select(PlatformAdpApiKey.Id).where(
        PlatformAdpApiKey.KeyHash == hashlib.sha256(provided.encode()).hexdigest(),
        PlatformAdpApiKey.RevokedAt.is_(None),
    ))).scalar_one_or_none()
    if key_id is None:
        raise AccountUnauthorized("连接器 API Key 无效")
    return str(key_id)
