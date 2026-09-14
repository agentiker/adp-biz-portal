"""ADP app registry: per-enterprise provider resolution + CRUD + encryption."""

from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from core.adp_app import create_adp_app as _create_adp_app, delete_adp_app, list_adp_apps, serialize_adp_app, update_adp_app
from core.error.platform import PlatformBadRequest
from model.platform import AdpAppStatus, PlatformAdpApp


async def create_adp_app(db, **kwargs):
    """Fill the required TC credentials so each test only states what it cares about."""
    kwargs.setdefault("secret_id", "AKID-test-secret-id")
    kwargs.setdefault("secret_key", "test-secret-key")
    kwargs.setdefault("secret_app_id", "1250000000")
    return await _create_adp_app(db, **kwargs)


def _database_url() -> str:
    url = os.environ.get("PLATFORM_TEST_DATABASE_URL")
    if not url:
        pytest.skip("设置 PLATFORM_TEST_DATABASE_URL 后运行 PostgreSQL 集成测试")
    return url


class _FakeVendor:
    def __init__(self, config, application_id):
        self.config = config
        self.application_id = application_id


@pytest_asyncio.fixture
async def adp_sessionmaker(monkeypatch):
    # Ensure Fernet keyring + a fake vendor so provider building is deterministic.
    from test.app_bootstrap import ensure_app
    ensure_app()
    from app_factory import TAgenticApp
    monkeypatch.setitem(TAgenticApp.vendors, "test-vendor", _FakeVendor)
    from integrations.adp import registry
    registry.clear_provider_cache()

    database_url = _database_url()
    schema = f"platform_adp_test_{uuid.uuid4().hex}"
    admin = create_async_engine(database_url, pool_pre_ping=True)
    async with admin.begin() as c:
        await c.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        await c.execute(text(f'CREATE SCHEMA "{schema}"'))
    await admin.dispose()
    engine = create_async_engine(
        database_url, pool_size=4, max_overflow=0, pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": f'"{schema}",public'}},
    )
    async with engine.begin() as c:
        await c.run_sync(lambda s: PlatformAdpApp.metadata.create_all(s, tables=[PlatformAdpApp.__table__], checkfirst=False))
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()
        cleanup = create_async_engine(database_url, pool_pre_ping=True)
        async with cleanup.begin() as c:
            await c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await cleanup.dispose()


def _fallback_provider():
    return SimpleNamespace(agent_id="env-default", application_id="ENV-APP")


@pytest.mark.asyncio
async def test_create_encrypts_and_serialize_hides_secret(adp_sessionmaker):
    async with adp_sessionmaker() as db:
        app = await create_adp_app(db, name="App A", application_id="APP-A", app_key="secret-key-A", vendor="test-vendor", agent_id="agent-a")
        await db.commit()
        assert app.Ciphertext and app.Fingerprint and "secret-key-A" not in app.Ciphertext
        payload = serialize_adp_app(app)
        assert "appKey" not in payload and "ciphertext" not in payload
        assert payload["applicationId"] == "APP-A" and payload["agentId"] == "agent-a"


@pytest.mark.asyncio
async def test_resolve_uses_enterprise_binding_then_default_then_fallback(adp_sessionmaker):
    from integrations.adp import registry
    async with adp_sessionmaker() as db:
        # No DB apps yet -> fallback (.env provider).
        prov = await registry.resolve_provider_for_enterprise(db, SimpleNamespace(AdpAppId=None), fallback=_fallback_provider)
        assert prov.application_id == "ENV-APP"

        default_app = await create_adp_app(db, name="Default", application_id="APP-DEF", app_key="k1", vendor="test-vendor", is_default=True)
        bound_app = await create_adp_app(db, name="Bound", application_id="APP-BOUND", app_key="k2", vendor="test-vendor")
        await db.commit()

        # No binding -> default app.
        prov = await registry.resolve_provider_for_enterprise(db, SimpleNamespace(AdpAppId=None), fallback=_fallback_provider)
        assert prov.application_id == "APP-DEF"

        # Bound -> the bound app.
        prov = await registry.resolve_provider_for_enterprise(db, SimpleNamespace(AdpAppId=bound_app.Id), fallback=_fallback_provider)
        assert prov.application_id == "APP-BOUND"


@pytest.mark.asyncio
async def test_cache_rebuilds_after_update(adp_sessionmaker):
    from integrations.adp import registry
    async with adp_sessionmaker() as db:
        app = await create_adp_app(db, name="App", application_id="APP-1", app_key="k1", vendor="test-vendor", agent_id="agent-1")
        await db.commit()
        p1 = await registry.resolve_provider_for_enterprise(db, SimpleNamespace(AdpAppId=app.Id), fallback=_fallback_provider)
        p2 = await registry.resolve_provider_for_enterprise(db, SimpleNamespace(AdpAppId=app.Id), fallback=_fallback_provider)
        assert p1 is p2  # cached
        await update_adp_app(db, adp_app_id=str(app.Id), agent_id="agent-2")
        await db.commit()
        p3 = await registry.resolve_provider_for_enterprise(db, SimpleNamespace(AdpAppId=app.Id), fallback=_fallback_provider)
        assert p3 is not p1 and p3.agent_id == "agent-2"


@pytest.mark.asyncio
async def test_set_default_is_exclusive_and_disable_clears_default(adp_sessionmaker):
    async with adp_sessionmaker() as db:
        a = await create_adp_app(db, name="A", application_id="APPA", app_key="k", vendor="test-vendor", is_default=True)
        b = await create_adp_app(db, name="B", application_id="APPB", app_key="k", vendor="test-vendor")
        await db.commit()
        # Promote B to default -> A must lose default.
        await update_adp_app(db, adp_app_id=str(b.Id), is_default=True)
        await db.commit()
        rows = {r.ApplicationId: r for r in await list_adp_apps(db)}
        assert rows["APPB"].IsDefault is True and rows["APPA"].IsDefault is False
        # Disable B -> default cleared.
        await update_adp_app(db, adp_app_id=str(b.Id), status=str(AdpAppStatus.DISABLED))
        await db.commit()
        rows = {r.ApplicationId: r for r in await list_adp_apps(db)}
        assert rows["APPB"].IsDefault is False and rows["APPB"].Status == str(AdpAppStatus.DISABLED)


@pytest.mark.asyncio
async def test_duplicate_application_id_rejected(adp_sessionmaker):
    async with adp_sessionmaker() as db:
        await create_adp_app(db, name="A", application_id="DUP", app_key="k", vendor="test-vendor")
        await db.commit()
        with pytest.raises(PlatformBadRequest):
            await create_adp_app(db, name="B", application_id="DUP", app_key="k", vendor="test-vendor")


@pytest.mark.asyncio
async def test_all_tc_secrets_required_on_create(adp_sessionmaker):
    async with adp_sessionmaker() as db:
        with pytest.raises(PlatformBadRequest, match="TC_SECRET_ID"):
            await _create_adp_app(
                db, name="A", application_id="APP-NO-SID", app_key="k",
                secret_id="", secret_key="skey", secret_app_id="sappid", vendor="test-vendor",
            )


@pytest.mark.asyncio
async def test_per_app_secrets_reach_vendor_config(adp_sessionmaker):
    from integrations.adp import registry
    async with adp_sessionmaker() as db:
        app = await create_adp_app(
            db, name="Secrets", application_id="APP-SEC", app_key="k",
            secret_id="AKID-per-app", secret_key="per-app-key", secret_app_id="9988",
            vendor="test-vendor",
        )
        await db.commit()
        prov = await registry.resolve_provider_for_enterprise(
            db, SimpleNamespace(AdpAppId=app.Id), fallback=_fallback_provider
        )
        assert prov.vendor.config["SecretId"] == "AKID-per-app"
        assert prov.vendor.config["SecretKey"] == "per-app-key"
        assert prov.vendor.config["SecretAppId"] == "9988"


@pytest.mark.asyncio
async def test_partial_secret_rotation_keeps_other_fields(adp_sessionmaker):
    from integrations.adp import registry
    async with adp_sessionmaker() as db:
        app = await create_adp_app(
            db, name="Rotate", application_id="APP-ROT", app_key="k",
            secret_id="sid-orig", secret_key="skey-orig", secret_app_id="appid-orig",
            vendor="test-vendor",
        )
        await db.commit()
        # Rotate only the secret_key; the others must survive.
        await update_adp_app(db, adp_app_id=str(app.Id), secret_key="skey-new")
        await db.commit()
        prov = await registry.resolve_provider_for_enterprise(
            db, SimpleNamespace(AdpAppId=app.Id), fallback=_fallback_provider
        )
        assert prov.vendor.config["SecretKey"] == "skey-new"
        assert prov.vendor.config["SecretId"] == "sid-orig"
        assert prov.vendor.config["SecretAppId"] == "appid-orig"
