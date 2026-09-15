"""Admin lifecycle and immediate connector revocation in an isolated schema."""
import json
import uuid

import pytest
from sqlalchemy import select
from core.adp_api_key import create_api_key, require_connector_key, serialize_api_key
from core.platform import AccountUnauthorized
from core.error.platform import PlatformForbidden
from model.account import Account, AccountRole, AccountStatus
from model.platform import PlatformAdpApiKey, PlatformAuditEvent
from test.integration.test_platform_worker_postgres import platform_sessionmaker
from test.integration.test_admin_conversations_postgres import _admin_context, _install_context, _request


@pytest.mark.asyncio
async def test_admin_key_lifecycle_and_permissions(platform_sessionmaker, monkeypatch):
    from test.app_bootstrap import ensure_app
    ensure_app()
    import router.platform as router
    account_id = uuid.uuid4()
    async with platform_sessionmaker() as db:
        db.add(Account(Id=account_id, Name="test admin", Role=AccountRole.ADMIN, Status=AccountStatus.ACTIVE))
        await db.commit()
        _install_context(monkeypatch, router, _admin_context(account_id))
        request = _request(db)
        request.json = {"name": "ADP connector"}
        response = await router.AdminAdpApiKeyListApi().post(request)
        assert response.status == 201
        assert response.headers['Cache-Control'] == 'no-store'
        created = json.loads(response.body)
        secret = created['apiKey']
        assert await require_connector_key(db, secret) == created['id']
        row = (await db.execute(select(PlatformAdpApiKey))).scalar_one()
        assert row.KeyHash != secret and secret not in str(serialize_api_key(row))
        listed = await router.AdminAdpApiKeyListApi().get(request)
        assert secret not in listed.body.decode() and 'apiKey' not in json.loads(listed.body)[0]
        _install_context(monkeypatch, router, _admin_context(account_id, manage=False))
        for method, args in [(router.AdminAdpApiKeyListApi().get, (request,)), (router.AdminAdpApiKeyListApi().post, (request,)), (router.AdminAdpApiKeyRevokeApi().post, (request, created['id']))]:
            with pytest.raises(PlatformForbidden):
                await method(*args)
        _install_context(monkeypatch, router, _admin_context(account_id))
        revoked = await router.AdminAdpApiKeyRevokeApi().post(request, created['id'])
        assert json.loads(revoked.body)['revokedAt']
        await router.AdminAdpApiKeyRevokeApi().post(request, created['id'])
        for invalid in [None, '', 'legacy-service-token', secret, secret[:-1] + '!']:
            with pytest.raises(AccountUnauthorized):
                await require_connector_key(db, invalid)
        _, replacement = await create_api_key(db, 'replacement')
        await db.commit()
        assert replacement != secret
        await require_connector_key(db, replacement)
        audits = (await db.execute(select(PlatformAuditEvent))).scalars().all()
        assert {a.Action for a in audits} == {'adp_api_key.create', 'adp_api_key.revoke'}
        assert all(secret not in str(a.to_dict()) for a in audits)
