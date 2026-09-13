"""Platform user single-enterprise association: create/change/unbind + guards."""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import core.platform as platform_core
from core.error.platform import PlatformBadRequest
from core.platform import create_platform_user, update_platform_user_access
from model.account import Account
from model.platform import (
    EnterpriseStatus,
    PlatformCredential,
    PlatformEnterprise,
    PlatformMembership,
    PlatformRole,
    PlatformUser,
)


def _database_url() -> str:
    url = os.environ.get("PLATFORM_TEST_DATABASE_URL")
    if not url:
        pytest.skip("设置 PLATFORM_TEST_DATABASE_URL 后运行 PostgreSQL 集成测试")
    return url


@pytest_asyncio.fixture
async def user_sessionmaker(monkeypatch):
    # Membership logic is under test; context revocation is exercised elsewhere.
    monkeypatch.setattr(platform_core, "revoke_account_execution_contexts", AsyncMock())
    database_url = _database_url()
    schema = f"platform_user_test_{uuid.uuid4().hex}"
    admin = create_async_engine(database_url, pool_pre_ping=True)
    async with admin.begin() as c:
        await c.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        await c.execute(text(f'CREATE SCHEMA "{schema}"'))
    await admin.dispose()
    engine = create_async_engine(
        database_url, pool_size=4, max_overflow=0, pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": f'"{schema}",public'}},
    )
    tables = [
        Account.__table__, PlatformEnterprise.__table__, PlatformUser.__table__,
        PlatformCredential.__table__, PlatformMembership.__table__,
    ]
    async with engine.begin() as c:
        await c.run_sync(lambda s: Account.metadata.create_all(s, tables=tables, checkfirst=False))
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()
        cleanup = create_async_engine(database_url, pool_pre_ping=True)
        async with cleanup.begin() as c:
            await c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await cleanup.dispose()


async def _enterprise(db, name: str, *, status=EnterpriseStatus.ACTIVE) -> PlatformEnterprise:
    ent = PlatformEnterprise(Id=uuid.uuid4(), Name=name, CustomerCode=f"C-{uuid.uuid4().hex[:8]}", Status=status)
    db.add(ent)
    await db.flush()
    return ent


async def _active_enterprise_ids(db, user_id) -> set[str]:
    rows = list((await db.execute(
        select(PlatformMembership.EnterpriseId).where(
            PlatformMembership.UserId == user_id, PlatformMembership.Active.is_(True)
        )
    )).scalars().all())
    return {str(r) for r in rows}


@pytest.mark.asyncio
async def test_create_requires_enterprise_for_all_roles(user_sessionmaker):
    async with user_sessionmaker() as db:
        with pytest.raises(PlatformBadRequest, match="必须绑定"):
            await create_platform_user(db, name="无企业", phone="13800000001", role=PlatformRole.STAFF, enterprise_id=None)


@pytest.mark.asyncio
async def test_change_enterprise_keeps_single_active_membership(user_sessionmaker):
    async with user_sessionmaker() as db:
        ent_a = await _enterprise(db, "企业A")
        ent_b = await _enterprise(db, "企业B")
        user, _ = await create_platform_user(db, name="张三", phone="13800000002", role=PlatformRole.STAFF, enterprise_id=str(ent_a.Id))
        await db.commit()
        assert await _active_enterprise_ids(db, user.Id) == {str(ent_a.Id)}

        # Switch to B -> A deactivated, exactly one active membership.
        await update_platform_user_access(db, user_id=str(user.Id), enterprise_id=str(ent_b.Id))
        await db.commit()
        assert await _active_enterprise_ids(db, user.Id) == {str(ent_b.Id)}


@pytest.mark.asyncio
async def test_unbind_clears_membership(user_sessionmaker):
    async with user_sessionmaker() as db:
        ent = await _enterprise(db, "企业A")
        user, _ = await create_platform_user(db, name="李四", phone="13800000003", role=PlatformRole.CUSTOMER, enterprise_id=str(ent.Id))
        await db.commit()
        await update_platform_user_access(db, user_id=str(user.Id), enterprise_id="")
        await db.commit()
        assert await _active_enterprise_ids(db, user.Id) == set()


@pytest.mark.asyncio
async def test_role_only_update_leaves_enterprise_unchanged(user_sessionmaker):
    async with user_sessionmaker() as db:
        ent = await _enterprise(db, "企业A")
        user, _ = await create_platform_user(db, name="王五", phone="13800000004", role=PlatformRole.STAFF, enterprise_id=str(ent.Id))
        await db.commit()
        await update_platform_user_access(db, user_id=str(user.Id), role=PlatformRole.OPS)
        await db.commit()
        assert await _active_enterprise_ids(db, user.Id) == {str(ent.Id)}


@pytest.mark.asyncio
async def test_reject_suspended_enterprise(user_sessionmaker):
    async with user_sessionmaker() as db:
        ent = await _enterprise(db, "企业A")
        suspended = await _enterprise(db, "停用企业", status=EnterpriseStatus.SUSPENDED)
        user, _ = await create_platform_user(db, name="赵六", phone="13800000005", role=PlatformRole.STAFF, enterprise_id=str(ent.Id))
        await db.commit()
        with pytest.raises(PlatformBadRequest, match="停用"):
            await update_platform_user_access(db, user_id=str(user.Id), enterprise_id=str(suspended.Id))
