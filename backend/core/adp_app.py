"""ADP application registry: create/update/list/delete configurable ADP apps.

The AppKey (and optional private endpoint) are stored Fernet-encrypted using the
same keyring as channel credentials; only non-secret fields are ever serialized
back to the Admin UI. At most one active app may be the platform default.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.channel_credentials import decrypt_ciphertext, encrypt_credential
from core.error.platform import PlatformBadRequest, PlatformNotFound
from model.platform import AdpAppStatus, PlatformAdpApp


_APPLICATION_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{1,63}")


def serialize_adp_app(row: PlatformAdpApp) -> dict[str, Any]:
    """Metadata only — the AppKey and ciphertext are never returned."""
    fingerprint = row.Fingerprint or ""
    return {
        "id": str(row.Id),
        "name": row.Name,
        "applicationId": row.ApplicationId,
        "vendor": row.Vendor,
        "serviceVendor": row.ServiceVendor,
        "agentId": row.AgentId,
        "status": row.Status,
        "isDefault": bool(row.IsDefault),
        "appKeyFingerprint": fingerprint[-8:] if fingerprint else "",
        "updatedAt": row.UpdatedAt.isoformat() if row.UpdatedAt else "",
    }


def _validate_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
        raise PlatformBadRequest("ADP 应用名称不能为空")
    return value.strip()


def _validate_application_id(value: Any) -> str:
    if not isinstance(value, str) or not _APPLICATION_ID_PATTERN.fullmatch(value.strip()):
        raise PlatformBadRequest("ApplicationId 格式不正确")
    return value.strip()


def _optional_text(value: Any, *, field: str, max_length: int, default: str | None = None) -> str | None:
    if value is None:
        return default
    if not isinstance(value, str):
        raise PlatformBadRequest(f"{field}格式不正确")
    trimmed = value.strip()
    if not trimmed:
        return default
    if len(trimmed) > max_length:
        raise PlatformBadRequest(f"{field}过长")
    return trimmed


def _require_secret(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlatformBadRequest(f"{field} 不能为空")
    return value.strip()


def _encrypt_secret(*, app_key: str, secret_id: str, secret_key: str, secret_app_id: str, private_url: str | None):
    payload: dict[str, str] = {
        "AppKey": app_key,
        "SecretId": secret_id,
        "SecretKey": secret_key,
        "SecretAppId": secret_app_id,
    }
    if private_url:
        payload["PrivateUrl"] = private_url
    return encrypt_credential(payload)


async def _clear_other_defaults(db: AsyncSession, *, keep_id: str | None) -> None:
    rows = list((await db.execute(
        select(PlatformAdpApp).where(PlatformAdpApp.IsDefault.is_(True))
    )).scalars().all())
    for row in rows:
        if keep_id is None or str(row.Id) != str(keep_id):
            row.IsDefault = False
    await db.flush()


async def list_adp_apps(db: AsyncSession) -> list[PlatformAdpApp]:
    return list((await db.execute(
        select(PlatformAdpApp).order_by(PlatformAdpApp.Name)
    )).scalars().all())


async def create_adp_app(
    db: AsyncSession,
    *,
    name: str,
    application_id: str,
    app_key: str,
    secret_id: str,
    secret_key: str,
    secret_app_id: str,
    vendor: Any = None,
    service_vendor: Any = None,
    agent_id: Any = None,
    private_url: Any = None,
    is_default: bool = False,
) -> PlatformAdpApp:
    name = _validate_name(name)
    application_id = _validate_application_id(application_id)
    app_key = _require_secret(app_key, field="AppKey")
    secret_id = _require_secret(secret_id, field="TC_SECRET_ID")
    secret_key = _require_secret(secret_key, field="TC_SECRET_KEY")
    secret_app_id = _require_secret(secret_app_id, field="TC_SECRET_APPID")
    duplicate = (await db.execute(
        select(PlatformAdpApp).where(PlatformAdpApp.ApplicationId == application_id)
    )).scalar_one_or_none()
    if duplicate is not None:
        raise PlatformBadRequest("ApplicationId 已存在")
    encrypted = _encrypt_secret(
        app_key=app_key, secret_id=secret_id, secret_key=secret_key,
        secret_app_id=secret_app_id,
        private_url=_optional_text(private_url, field="PrivateUrl", max_length=512),
    )
    if is_default:
        await _clear_other_defaults(db, keep_id=None)
    app = PlatformAdpApp(
        Name=name,
        ApplicationId=application_id,
        Vendor=_optional_text(vendor, field="Vendor", max_length=32, default="Tencent"),
        ServiceVendor=_optional_text(service_vendor, field="ServiceVendor", max_length=32, default="ChinaTencentCloud"),
        AgentId=_optional_text(agent_id, field="AgentId", max_length=128, default="platform-default"),
        Ciphertext=encrypted.ciphertext,
        KeyVersion=encrypted.key_version,
        Fingerprint=encrypted.fingerprint,
        Status=AdpAppStatus.ACTIVE,
        IsDefault=bool(is_default),
    )
    db.add(app)
    await db.flush()
    await db.refresh(app)
    return app


async def update_adp_app(
    db: AsyncSession,
    *,
    adp_app_id: str,
    name: Any = None,
    app_key: Any = None,
    secret_id: Any = None,
    secret_key: Any = None,
    secret_app_id: Any = None,
    vendor: Any = None,
    service_vendor: Any = None,
    agent_id: Any = None,
    private_url: Any = None,
    status: Any = None,
    is_default: Any = None,
) -> PlatformAdpApp:
    app = await db.get(PlatformAdpApp, adp_app_id)
    if app is None:
        raise PlatformNotFound("ADP 应用不存在")
    if name is not None:
        app.Name = _validate_name(name)
    if vendor is not None:
        app.Vendor = _optional_text(vendor, field="Vendor", max_length=32, default="Tencent")
    if service_vendor is not None:
        app.ServiceVendor = _optional_text(service_vendor, field="ServiceVendor", max_length=32, default="ChinaTencentCloud")
    if agent_id is not None:
        app.AgentId = _optional_text(agent_id, field="AgentId", max_length=128, default="platform-default")
    # Rotate secrets: any provided field is merged over the current decrypted
    # payload, so the operator can update just one credential at a time.
    rotate = {
        key: value
        for key, value in {
            "AppKey": app_key, "SecretId": secret_id,
            "SecretKey": secret_key, "SecretAppId": secret_app_id,
            "PrivateUrl": private_url,
        }.items()
        if isinstance(value, str) and value.strip()
    }
    if rotate:
        current = json.loads(decrypt_ciphertext(app.Ciphertext, app.KeyVersion, fingerprint=app.Fingerprint))
        merged = {**current, **{k: v.strip() for k, v in rotate.items()}}
        encrypted = _encrypt_secret(
            app_key=merged["AppKey"], secret_id=merged["SecretId"],
            secret_key=merged["SecretKey"], secret_app_id=merged["SecretAppId"],
            private_url=merged.get("PrivateUrl"),
        )
        app.Ciphertext = encrypted.ciphertext
        app.KeyVersion = encrypted.key_version
        app.Fingerprint = encrypted.fingerprint
    if status is not None:
        if status not in (str(AdpAppStatus.ACTIVE), str(AdpAppStatus.DISABLED)):
            raise PlatformBadRequest("状态不正确")
        app.Status = status
        if status == str(AdpAppStatus.DISABLED):
            app.IsDefault = False
    if is_default is not None:
        if bool(is_default):
            if str(app.Status) != str(AdpAppStatus.ACTIVE):
                raise PlatformBadRequest("停用的应用不能设为默认")
            await _clear_other_defaults(db, keep_id=str(app.Id))
            app.IsDefault = True
        else:
            app.IsDefault = False
    await db.flush()
    await db.refresh(app)
    return app


async def delete_adp_app(db: AsyncSession, *, adp_app_id: str) -> None:
    app = await db.get(PlatformAdpApp, adp_app_id)
    if app is None:
        raise PlatformNotFound("ADP 应用不存在")
    # Enterprises bound to this app revert to the default (FK ON DELETE SET NULL).
    await db.delete(app)
    await db.flush()
