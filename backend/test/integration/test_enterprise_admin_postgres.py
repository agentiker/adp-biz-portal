"""Enterprise admin: new contact/identity fields — create + update validation."""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from core.error.platform import PlatformBadRequest, PlatformNotFound
from core.platform import create_enterprise, update_enterprise
from model.platform import PlatformEnterprise


VALID_USCC = "91110000MA01ABCDEF"  # 18 chars, GB32100 charset
VALID_USCC_2 = "91310000MA01WXYQ12"


def _database_url() -> str:
    url = os.environ.get("PLATFORM_TEST_DATABASE_URL")
    if not url:
        pytest.skip("设置 PLATFORM_TEST_DATABASE_URL 后运行 PostgreSQL 集成测试")
    return url


@pytest_asyncio.fixture
async def ent_sessionmaker():
    database_url = _database_url()
    schema = f"platform_ent_test_{uuid.uuid4().hex}"
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
        await c.run_sync(lambda s: PlatformEnterprise.metadata.create_all(
            s, tables=[PlatformEnterprise.__table__], checkfirst=False))
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()
        cleanup = create_async_engine(database_url, pool_pre_ping=True)
        async with cleanup.begin() as c:
            await c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await cleanup.dispose()


@pytest.mark.asyncio
async def test_create_enterprise_stores_new_fields(ent_sessionmaker):
    async with ent_sessionmaker() as db:
        ent = await create_enterprise(
            db, name="示例企业", customer_code="CUST-1",
            unified_social_credit_code=VALID_USCC.lower(),  # normalized to upper
            contact_person="张三", contact_phone="13800000000",
        )
        await db.commit()
        assert ent.UnifiedSocialCreditCode == VALID_USCC
        assert ent.ContactPerson == "张三" and ent.ContactPhone == "13800000000"


@pytest.mark.asyncio
async def test_uscc_is_required_and_format_checked(ent_sessionmaker):
    async with ent_sessionmaker() as db:
        with pytest.raises(PlatformBadRequest):
            await create_enterprise(db, name="A", customer_code="C-A", unified_social_credit_code="")
        with pytest.raises(PlatformBadRequest):
            await create_enterprise(db, name="A", customer_code="C-A", unified_social_credit_code="not-18-chars")


@pytest.mark.asyncio
async def test_uscc_must_be_unique(ent_sessionmaker):
    async with ent_sessionmaker() as db:
        await create_enterprise(db, name="A", customer_code="C-A", unified_social_credit_code=VALID_USCC)
        await db.commit()
        with pytest.raises(PlatformBadRequest):
            await create_enterprise(db, name="B", customer_code="C-B", unified_social_credit_code=VALID_USCC)


@pytest.mark.asyncio
async def test_contact_fields_optional_and_updatable(ent_sessionmaker):
    async with ent_sessionmaker() as db:
        ent = await create_enterprise(db, name="A", customer_code="C-A", unified_social_credit_code=VALID_USCC)
        await db.commit()
        assert ent.ContactPerson is None and ent.ContactPhone is None
        updated = await update_enterprise(
            db, enterprise_id=str(ent.Id), name="A2",
            contact_person="李四", contact_phone="13900000000",
        )
        await db.commit()
        assert updated.Name == "A2" and updated.ContactPerson == "李四"
        # Clearing a contact field with an empty string.
        cleared = await update_enterprise(db, enterprise_id=str(ent.Id), contact_phone="")
        await db.commit()
        assert cleared.ContactPhone is None


@pytest.mark.asyncio
async def test_update_rejects_duplicate_uscc_and_missing_enterprise(ent_sessionmaker):
    async with ent_sessionmaker() as db:
        a = await create_enterprise(db, name="A", customer_code="C-A", unified_social_credit_code=VALID_USCC)
        await create_enterprise(db, name="B", customer_code="C-B", unified_social_credit_code=VALID_USCC_2)
        await db.commit()
        with pytest.raises(PlatformBadRequest):
            await update_enterprise(db, enterprise_id=str(a.Id), unified_social_credit_code=VALID_USCC_2)
        with pytest.raises(PlatformNotFound):
            await update_enterprise(db, enterprise_id=str(uuid.uuid4()), name="X")
