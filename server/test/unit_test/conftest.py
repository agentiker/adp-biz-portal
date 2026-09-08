import hmac
import hashlib
import time
import uuid
from urllib.parse import quote

import pytest
import pytest_asyncio
from sqlalchemy import select

from config import tagentic_config
from test.app_bootstrap import ensure_app
from core.account import CoreAccount
from core.session import SessionToken
from model.account import AccountRole, AccountThirdParty
from model.platform import (
    EnterpriseExternalAccount,
    EnterpriseStatus,
    IntegrationConnection,
    IntegrationConnectionStatus,
    PlatformEnterprise,
)


@pytest.fixture(scope="session")
def app():
    return ensure_app()


@pytest.fixture(scope="session")
def account():
    _account = {
    }
    return _account


@pytest_asyncio.fixture(scope="session")
async def auth_token(app, account):
    customer_id = "123456"
    name = "test"
    extra_info = '{"Level":1}'
    timestamp = int(time.time())
    msg = f'{customer_id}{name}{extra_info}{timestamp}'
    sign = hmac.new(
        tagentic_config.CUSTOMER_ACCOUNT_SECRET_KEY.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    # create account
    request, response = await app.asgi_client.get(
        (
            f"/account/customer?CustomerId={quote(customer_id)}&Name={quote(name)}&"
            f"Timestamp={str(timestamp)}&ExtraInfo={quote(extra_info)}&Code={quote(sign)}"
        )
    )
    print(response.cookies)
    assert request.method.lower() == "get"
    assert 'token' in response.cookies
    assert response.status == 302

    token = response.cookies['token']
    account_id = SessionToken.check(token)["AccountId"]
    application_id = next(iter(app.apps))
    async with app.config["sessionmaker"]() as db:
        customer = (
            await db.execute(
                select(AccountThirdParty).where(
                    AccountThirdParty.AccountId == account_id,
                    AccountThirdParty.Provider == "customer",
                )
            )
        ).scalar_one()
        enterprise = (
            await db.execute(
                select(PlatformEnterprise).where(
                    PlatformEnterprise.CustomerCode == customer.OpenId,
                )
            )
        ).scalar_one_or_none()
        if enterprise is None:
            enterprise = PlatformEnterprise(
                Name="Legacy API Test Enterprise",
                CustomerCode=customer.OpenId,
                Status=EnterpriseStatus.ACTIVE,
            )
            db.add(enterprise)
            await db.flush()

        connection = (
            await db.execute(
                select(IntegrationConnection).where(
                    IntegrationConnection.ApplicationId == application_id,
                )
            )
        ).scalar_one_or_none()
        if connection is None:
            vendor_app = app.apps[application_id]
            config = getattr(vendor_app, "config", {}) or {}
            connection = IntegrationConnection(
                ApplicationId=application_id,
                UpstreamAppId=str(config.get("AppId") or application_id),
                Vendor=str(config.get("Vendor") or "Tencent"),
                Status=IntegrationConnectionStatus.ACTIVE,
            )
            db.add(connection)
            await db.flush()

        external = (
            await db.execute(
                select(EnterpriseExternalAccount).where(
                    EnterpriseExternalAccount.EnterpriseId == enterprise.Id,
                    EnterpriseExternalAccount.ConnectionId == connection.Id,
                )
            )
        ).scalar_one_or_none()
        if external is None:
            external = EnterpriseExternalAccount(
                EnterpriseId=enterprise.Id,
                ConnectionId=connection.Id,
                ExternalAccountId=f"legacy-test-{uuid.uuid4()}",
                WorkspaceId="workspace-1",
                Status=IntegrationConnectionStatus.ACTIVE,
            )
            db.add(external)
        else:
            # Keep reused local fixtures aligned with the binding contract.
            external.WorkspaceId = "workspace-1"
        await db.commit()

    return token


@pytest_asyncio.fixture(scope="session")
async def admin_auth_token(app):
    """Create a legacy admin token for compatibility-route regression tests."""
    async with app.config["sessionmaker"]() as db:
        account = await CoreAccount.create_account(db, name="legacy-security-admin")
        account.Role = AccountRole.ADMIN
        await db.commit()
        return await CoreAccount.login(db, account, "127.0.0.1")
