"""Resolve the ADP provider for a given enterprise from the DB app registry.

Multiple ADP applications can be configured in the database (with Fernet-encrypted
AppKeys). Each enterprise may bind one via ``PlatformEnterprise.AdpAppId``; a
platform default (``IsDefault``) is used otherwise. When no DB app applies (empty
registry, no default), the caller's ``fallback`` — the server ``.env`` single
provider — is used, so behavior is unchanged until apps are configured.

Providers are cached per app id + ``UpdatedAt`` so an Admin edit rebuilds the
vendor with the new credentials without a restart.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from sqlalchemy import select

from core.channel_credentials import decrypt_ciphertext
from integrations.adp.provider import ADPAgentProvider, AgentProvider
from model.platform import AdpAppStatus, PlatformAdpApp


logger = logging.getLogger(__name__)


class AdpAppConfigError(RuntimeError):
    """A configured ADP application cannot be turned into a usable provider."""


# app_id -> (updated_at_iso, provider). Rebuilt when the row's UpdatedAt changes.
_provider_cache: dict[str, tuple[str, AgentProvider]] = {}


def _cache_version(app: PlatformAdpApp) -> str:
    return app.UpdatedAt.isoformat() if getattr(app, "UpdatedAt", None) else ""


async def _load_app(db: Any, enterprise: Any) -> PlatformAdpApp | None:
    """Return the enterprise's bound active app, else the active default, else None."""
    app_id = getattr(enterprise, "AdpAppId", None)
    if app_id is not None:
        bound = await db.get(PlatformAdpApp, app_id)
        if bound is not None and str(bound.Status) == str(AdpAppStatus.ACTIVE):
            return bound
        # A bound-but-missing/disabled app falls through to the platform default.
    return (await db.execute(
        select(PlatformAdpApp).where(
            PlatformAdpApp.IsDefault.is_(True),
            PlatformAdpApp.Status == AdpAppStatus.ACTIVE,
        )
    )).scalars().first()


def _build_provider(app: PlatformAdpApp) -> AgentProvider:
    from app_factory import TAgenticApp

    try:
        payload = json.loads(decrypt_ciphertext(app.Ciphertext, app.KeyVersion, fingerprint=app.Fingerprint))
    except Exception as exc:  # noqa: BLE001 - never leak ciphertext/plaintext
        raise AdpAppConfigError(f"adp app {app.ApplicationId} secret unavailable: {type(exc).__name__}") from exc
    if not isinstance(payload, dict) or not str(payload.get("AppKey") or "").strip():
        raise AdpAppConfigError(f"adp app {app.ApplicationId} is missing AppKey")
    vendor_cls = TAgenticApp.vendors.get(app.Vendor)
    if vendor_cls is None:
        raise AdpAppConfigError(f"adp app vendor not registered: {app.Vendor}")
    config: dict[str, Any] = {
        "ApplicationId": app.ApplicationId,
        "Vendor": app.Vendor,
        "AppKey": str(payload["AppKey"]).strip(),
        "ServiceVendor": app.ServiceVendor,
    }
    # Per-app Tencent Cloud credentials override the global .env values so each
    # ADP application signs its own API calls (see vendor tc_config injection).
    for payload_key, config_key in (
        ("SecretId", "SecretId"),
        ("SecretKey", "SecretKey"),
        ("SecretAppId", "SecretAppId"),
    ):
        value = str(payload.get(payload_key) or "").strip()
        if value:
            config[config_key] = value
    private_url = str(payload.get("PrivateUrl") or "").strip()
    if private_url:
        config["PrivateUrl"] = private_url
    vendor = vendor_cls(config, app.ApplicationId)
    agent_id = (app.AgentId or "platform-default").strip() or "platform-default"
    return ADPAgentProvider(agent_id=agent_id, application_id=app.ApplicationId, vendor=vendor)


async def resolve_provider_for_enterprise(
    db: Any, enterprise: Any, *, fallback: Callable[[], AgentProvider | None]
) -> AgentProvider | None:
    """Resolve the provider for ``enterprise``; ``fallback`` supplies the .env one."""
    app = await _load_app(db, enterprise)
    if app is None:
        return fallback()
    cache_key = str(app.Id)
    version = _cache_version(app)
    cached = _provider_cache.get(cache_key)
    if cached is not None and cached[0] == version:
        return cached[1]
    provider = _build_provider(app)
    _provider_cache[cache_key] = (version, provider)
    return provider


def clear_provider_cache() -> None:
    """Drop the provider cache (used by Admin writes and tests)."""
    _provider_cache.clear()
