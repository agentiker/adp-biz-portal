from types import SimpleNamespace

import pytest

from core.adp_app import _provider_settings, update_adp_app
from core.error.platform import PlatformBadRequest
from integrations.adp.registry import (
    AdpAppConfigError,
    list_provider_types,
    normalize_provider_type,
    register_provider_factory,
)
from integrations.crm.base import CrmCapabilities, CrmConnectionConfig
from integrations.crm.registry import CrmConnectorRegistry, CrmRegistryError
from model.platform import AdpProviderType


def test_legacy_adp_vendor_maps_to_stable_provider_type():
    assert normalize_provider_type(None, vendor="Tencent") == str(AdpProviderType.TENCENT)
    assert normalize_provider_type("ChinaTencentCloud") == str(AdpProviderType.TENCENT)
    assert normalize_provider_type("ALIYUN_ADP") == "aliyun_adp"
    assert str(AdpProviderType.TENCENT) in list_provider_types()


def test_adp_provider_factory_registration_is_explicit():
    key = "test_adp_provider"

    def factory(app, credentials):
        return SimpleNamespace(app=app, credentials=credentials)

    register_provider_factory(key, factory)
    with pytest.raises(AdpAppConfigError):
        register_provider_factory(key, factory)


def test_crm_registry_normalizes_and_builds_connector():
    registry = CrmConnectorRegistry()

    class Connector:
        capabilities = CrmCapabilities(resolve_identity=True)

    registry.register("Salesforce_CRM", lambda config: Connector())
    connector = registry.build(CrmConnectionConfig(provider_type="salesforce", tenant_id="tenant-1"))
    assert connector.capabilities.resolve_identity is True
    assert registry.list_provider_types() == ("salesforce",)

    with pytest.raises(CrmRegistryError):
        registry.get_factory("missing")


def test_provider_settings_reject_secret_like_fields():
    assert _provider_settings({"region": "cn-shanghai", "retry": 3}) == {
        "region": "cn-shanghai",
        "retry": 3,
    }
    with pytest.raises(PlatformBadRequest, match="credentials"):
        _provider_settings({"apiKey": "must-be-encrypted"})


@pytest.mark.asyncio
async def test_switching_provider_requires_new_credentials():
    app = SimpleNamespace(
        Id="app-id",
        ProviderType="tencent_adp",
        ProviderSchemaVersion=1,
        ProviderSettings={},
        Status="active",
        IsDefault=False,
    )

    class Db:
        async def get(self, model, identifier):
            return app

        async def flush(self):
            return None

        async def refresh(self, row):
            return None

    with pytest.raises(PlatformBadRequest, match="新 credentials"):
        await update_adp_app(
            Db(),
            adp_app_id="app-id",
            provider_type="aliyun_adp",
        )
