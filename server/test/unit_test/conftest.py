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
    PlatformMembership,
    PlatformRole,
    PlatformUser,
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

        # 管理员账号在同一个 DB 块里建好。单独用一个 session 级 async fixture 去写库
        # 会让连接池在 session 事件循环里被占用，随后测试体在自己的循环里复用同一
        # 连接就会抛 "attached to a different loop"（测试基座既有缺陷，见
        # ROADMAP M2-TEST-FIX-01）。复用这里唯一的一次 DB 会话即可绕开。
        admin_account = await CoreAccount.create_account(db, name="legacy-security-admin")
        admin_account.Role = AccountRole.ADMIN
        await db.flush()
        admin_platform_user = PlatformUser(
            AccountId=admin_account.Id,
            Name="legacy-security-admin",
            PhoneNormalized=f"+8613{uuid.uuid4().int % 10**9:09d}",
            PhoneMasked="138****0000",
            Role=PlatformRole.ADMIN,
            Status="active",
        )
        db.add(admin_platform_user)
        await db.flush()
        # 与普通账号同企业：管理员没有企业绑定时只能走 "未绑定本地管理员" 兜底，
        # 那条兜底的 workspace_id 为 None，需要 workspace 的文件类路由会 403，
        # 就测不到真正要测的路径校验了。
        db.add(
            PlatformMembership(
                UserId=admin_platform_user.Id,
                EnterpriseId=enterprise.Id,
                MembershipRole=PlatformRole.ADMIN,
                Active=True,
            )
        )
        account["admin_token"] = await CoreAccount.login(db, admin_account, "127.0.0.1")

        await db.commit()

    return token


@pytest.fixture
def admin_auth_token(auth_token, account):
    """Legacy admin token, created alongside `auth_token` in the same DB session."""
    return account["admin_token"]
