"""Resolve the ADP provider for a given enterprise from the DB app registry.

Multiple ADP applications can be configured in the database (with Fernet-encrypted
AppKeys). Each enterprise may bind one via ``PlatformEnterprise.AdpAppId``; a
platform default (``IsDefault``) is used otherwise. No configured application fails closed. The optional fallback is only an
explicit dependency injection hook for local tests, never a runtime .env source.

Providers are cached per app id + ``UpdatedAt`` so an Admin edit rebuilds the
vendor with the new credentials without a restart.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any, Callable

from sqlalchemy import select

from core.channel_credentials import decrypt_ciphertext
from integrations.adp.provider import ADPAgentProvider, AgentProvider
from model.platform import AdpAppStatus, AdpProviderType, PlatformAdpApp


logger = logging.getLogger(__name__)


class AdpAppConfigError(RuntimeError):
    """A configured ADP application cannot be turned into a usable provider."""


# app_id -> (updated_at_iso, provider). Rebuilt when the row's UpdatedAt changes.
_provider_cache: dict[str, tuple[str, AgentProvider]] = {}

# Provider factories are keyed by a stable platform identifier. They receive
# decrypted credentials only inside this module and must return the existing
# AgentProvider contract. New cloud providers can register independently of the
# enterprise resolution logic.
AdpProviderFactory = Callable[[PlatformAdpApp, Mapping[str, Any]], AgentProvider]
_provider_factories: dict[str, AdpProviderFactory] = {}


def normalize_provider_type(provider_type: Any, *, vendor: Any = None) -> str:
    """Return a stable provider key, including compatibility for old rows."""
    aliases = {
        "tencent": str(AdpProviderType.TENCENT),
        "tencent_adp": str(AdpProviderType.TENCENT),
        "chinatencentadp": str(AdpProviderType.TENCENT),
        "chinatencentcloud": str(AdpProviderType.TENCENT),
    }
    value = str(provider_type or "").strip().lower()
    if value:
        return aliases.get(value, value)
    legacy = str(vendor or "").strip().lower()
    return aliases.get(legacy, legacy)


def register_provider_factory(
    provider_type: str,
    factory: AdpProviderFactory,
    *,
    replace: bool = False,
) -> AdpProviderFactory:
    key = normalize_provider_type(provider_type)
    if not key or not callable(factory):
        raise AdpAppConfigError("ADP provider requires a provider type and callable factory")
    if key in _provider_factories and not replace:
        raise AdpAppConfigError(f"ADP provider already registered: {key}")
    _provider_factories[key] = factory
    return factory


def list_provider_types() -> tuple[str, ...]:
    return tuple(sorted(_provider_factories))


def _cache_version(app: PlatformAdpApp) -> str:
    return app.UpdatedAt.isoformat() if getattr(app, "UpdatedAt", None) else ""


async def _load_app(db: Any, enterprise: Any) -> PlatformAdpApp | None:
    """Return the enterprise's bound active app, else the active default, else None."""
    app_id = getattr(enterprise, "AdpAppId", None)
    if app_id is not None:
        bound = await db.get(PlatformAdpApp, app_id)
        if bound is not None and str(bound.Status) == str(AdpAppStatus.ACTIVE):
            return bound
        raise AdpAppConfigError("bound ADP application is unavailable")
    return (await db.execute(
        select(PlatformAdpApp).where(
            PlatformAdpApp.IsDefault.is_(True),
            PlatformAdpApp.Status == AdpAppStatus.ACTIVE,
        )
    )).scalars().first()


def _build_tencent_provider(app: PlatformAdpApp, payload: Mapping[str, Any]) -> AgentProvider:
    from app_factory import TAgenticApp
    if not isinstance(payload, dict) or not str(payload.get("AppKey") or "").strip():
        raise AdpAppConfigError(f"adp app {app.ApplicationId} is missing AppKey")
    if any(not str(payload.get(key) or "").strip() for key in ("SecretId", "SecretKey", "SecretAppId")):
        raise AdpAppConfigError("ADP application requires all per-application signing credentials")
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


def _build_provider(app: PlatformAdpApp) -> AgentProvider:
    try:
        payload = json.loads(decrypt_ciphertext(app.Ciphertext, app.KeyVersion, fingerprint=app.Fingerprint))
    except Exception as exc:  # noqa: BLE001 - never leak ciphertext/plaintext
        raise AdpAppConfigError(f"adp app {app.ApplicationId} secret unavailable: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise AdpAppConfigError(f"adp app {app.ApplicationId} credentials are invalid")
    provider_type = normalize_provider_type(
        getattr(app, "ProviderType", None), vendor=getattr(app, "Vendor", None)
    )
    factory = _provider_factories.get(provider_type)
    if factory is None:
        raise AdpAppConfigError(f"adp provider not registered: {provider_type or '<empty>'}")
    try:
        return factory(app, payload)
    except AdpAppConfigError:
        raise
    except Exception as exc:  # noqa: BLE001 - keep provider details out of API responses
        raise AdpAppConfigError(f"adp provider {provider_type} configuration invalid: {type(exc).__name__}") from exc


async def resolve_provider_for_enterprise(
    db: Any, enterprise: Any, *, fallback: Callable[[], AgentProvider | None] | None = None
) -> AgentProvider | None:
    """Resolve a DB application, or an explicitly injected test provider."""
    app = await _load_app(db, enterprise)
    if app is None:
        injected = fallback() if fallback is not None else None
        if injected is not None:
            return injected
        raise AdpAppConfigError("configure an active ADP application in Admin")
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


# Tencent remains the built-in provider. Aliyun and Volcengine are deliberately
# not registered until their external API contracts and credentials are available.
register_provider_factory(str(AdpProviderType.TENCENT), _build_tencent_provider)
