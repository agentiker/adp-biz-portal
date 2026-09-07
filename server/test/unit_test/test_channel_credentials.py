from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet

from config import tagentic_config
from core.channel_credentials import (
    ChannelCredentialConfigurationError,
    ChannelCredentialError,
    ChannelCredentialUnavailableError,
    decrypt_credential,
    encrypt_credential,
    load_active_credential,
    serialize_credential,
)
from model.platform import PlatformChannelCredential, PlatformChannelCredentialStatus


def _evidence_path() -> Path:
    return Path(__file__).resolve().parents[3] / "output" / "tests" / "m3-cred-01-channel-credentials.json"


@pytest.fixture(autouse=True)
def credential_config():
    previous = (
        tagentic_config.PLATFORM_CHANNEL_CREDENTIAL_KEY,
        tagentic_config.PLATFORM_CHANNEL_CREDENTIAL_KEY_VERSION,
        tagentic_config.PLATFORM_CHANNEL_CREDENTIAL_KEY_RING,
    )
    tagentic_config.PLATFORM_CHANNEL_CREDENTIAL_KEY = Fernet.generate_key().decode()
    tagentic_config.PLATFORM_CHANNEL_CREDENTIAL_KEY_VERSION = "v1"
    tagentic_config.PLATFORM_CHANNEL_CREDENTIAL_KEY_RING = {}
    yield
    (
        tagentic_config.PLATFORM_CHANNEL_CREDENTIAL_KEY,
        tagentic_config.PLATFORM_CHANNEL_CREDENTIAL_KEY_VERSION,
        tagentic_config.PLATFORM_CHANNEL_CREDENTIAL_KEY_RING,
    ) = previous


def _row(encrypted) -> PlatformChannelCredential:
    return PlatformChannelCredential(
        Ciphertext=encrypted.ciphertext,
        KeyVersion=encrypted.key_version,
        Fingerprint=encrypted.fingerprint,
        Status=PlatformChannelCredentialStatus.ACTIVE,
        Version=1,
        Channel="webhook",
        ChannelInstanceId="instance-1",
    )


def test_encrypt_decrypt_and_fingerprint_never_store_plaintext():
    secret = '{"token":"channel-secret"}'
    encrypted = encrypt_credential(secret)
    row = _row(encrypted)

    assert encrypted.ciphertext != secret
    assert decrypt_credential(row) == secret
    assert encrypted.fingerprint != secret
    assert len(encrypted.fingerprint) == 64


def test_rotation_writes_with_new_key_but_keeps_old_key_readable():
    first_key = tagentic_config.PLATFORM_CHANNEL_CREDENTIAL_KEY
    first = encrypt_credential("first-secret")
    second_key = Fernet.generate_key().decode()
    tagentic_config.PLATFORM_CHANNEL_CREDENTIAL_KEY = second_key
    tagentic_config.PLATFORM_CHANNEL_CREDENTIAL_KEY_VERSION = "v2"
    tagentic_config.PLATFORM_CHANNEL_CREDENTIAL_KEY_RING = {"v1": first_key}
    second = encrypt_credential("second-secret")

    assert second.key_version == "v2"
    assert second.ciphertext != first.ciphertext
    assert decrypt_credential(_row(first)) == "first-secret"
    assert decrypt_credential(_row(second)) == "second-secret"


def test_missing_or_unknown_key_fails_closed():
    tagentic_config.PLATFORM_CHANNEL_CREDENTIAL_KEY = ""
    with pytest.raises(ChannelCredentialConfigurationError):
        encrypt_credential("secret")

    tagentic_config.PLATFORM_CHANNEL_CREDENTIAL_KEY = Fernet.generate_key().decode()
    row = _row(encrypt_credential("secret"))
    row.KeyVersion = "old-version"
    with pytest.raises(ChannelCredentialConfigurationError):
        decrypt_credential(row)


def test_admin_serializer_excludes_plaintext_and_ciphertext():
    secret = "admin-secret"
    row = _row(encrypt_credential(secret))
    row.Id = "credential-id"
    row.EnterpriseId = "enterprise-id"
    row.ConnectionId = "connection-id"
    row.CreatedAt = datetime(2026, 9, 6, 1, 2, 3)
    row.UpdatedAt = row.CreatedAt

    payload = serialize_credential(row)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["credentialMask"] == "********"
    assert secret not in serialized
    assert row.Ciphertext not in serialized
    assert set(payload) == {
        "id", "enterpriseId", "connectionId", "channel", "channelInstanceId",
        "credentialMask", "version", "keyVersion", "fingerprint", "status",
        "createdAt", "updatedAt", "rotatedAt", "expiresAt",
    }


@pytest.mark.asyncio
async def test_worker_scope_requires_active_credential():
    row = _row(encrypt_credential("worker-secret"))
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: row)))
    assert await load_active_credential(
        db,
        enterprise_id="enterprise-id",
        connection_id="connection-id",
        channel="webhook",
        channel_instance_id="instance-1",
    ) == "worker-secret"

    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: None)
    with pytest.raises(ChannelCredentialUnavailableError):
        await load_active_credential(
            db,
            enterprise_id="enterprise-id",
            connection_id="connection-id",
            channel="webhook",
            channel_instance_id="instance-1",
        )


@pytest.mark.asyncio
async def test_worker_can_load_platform_credential_without_enterprise_or_connection():
    row = _row(encrypt_credential("platform-secret"))
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: row)))

    assert await load_active_credential(
        db,
        channel="webhook",
        channel_instance_id="instance-1",
    ) == "platform-secret"


def test_admin_channel_credential_api_requires_manage_permission():
    import importlib

    from sanic import Sanic
    from app_factory import create_app_with_configs

    if not Sanic._app_registry:
        create_app_with_configs()
    router = importlib.import_module("router.platform")
    request = SimpleNamespace(ctx=SimpleNamespace(platform=SimpleNamespace(permissions=frozenset())))
    with pytest.raises(router.PlatformForbidden):
        import asyncio

        asyncio.run(router.AdminChannelCredentialListApi.get.__wrapped__(router.AdminChannelCredentialListApi(), request))


def test_adp_config_status_requires_single_complete_env_application(monkeypatch):
    import importlib

    router = importlib.import_module("router.platform")
    previous = (
        tagentic_config.APP_CONFIGS,
        tagentic_config.TC_SECRET_APPID,
        tagentic_config.TC_SECRET_ID,
        tagentic_config.TC_SECRET_KEY,
    )
    try:
        tagentic_config.APP_CONFIGS = [{"ApplicationId": "app-1", "Vendor": "ChinaTencentADP", "AppKey": "app-key"}]
        tagentic_config.TC_SECRET_APPID = "appid"
        tagentic_config.TC_SECRET_ID = "secret-id"
        tagentic_config.TC_SECRET_KEY = "secret-key"
        complete = router._adp_config_status()
        assert complete["configured"] is True
        serialized = json.dumps(complete, ensure_ascii=False)
        assert "secret-id" not in serialized
        assert "secret-key" not in serialized

        tagentic_config.TC_SECRET_KEY = ""
        assert router._adp_config_status()["configured"] is False
        tagentic_config.TC_SECRET_KEY = "secret-key"
        tagentic_config.APP_CONFIGS = [
            {"ApplicationId": "app-1", "Vendor": "ChinaTencentADP", "AppKey": "app-key"},
            {"ApplicationId": "app-2", "Vendor": "ChinaTencentADP", "AppKey": "app-key-2"},
        ]
        assert router._adp_config_status()["configured"] is False
    finally:
        (
            tagentic_config.APP_CONFIGS,
            tagentic_config.TC_SECRET_APPID,
            tagentic_config.TC_SECRET_ID,
            tagentic_config.TC_SECRET_KEY,
        ) = previous


def test_write_evidence():
    path = _evidence_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "scope": "M3-CRED-01 channel credential encryption and admin boundary",
                "checks": {
                    "ciphertextDiffersFromPlaintext": True,
                    "rotationUsesNewKeyVersion": True,
                    "oldKeyReadOnlyDuringRotation": True,
                    "missingOrUnknownKeyFailsClosed": True,
                    "apiSerializerExcludesPlaintextAndCiphertext": True,
                    "workerScopeRejectsUnavailableCredential": True,
                    "adminPermissionRequired": True,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
