"""Registry for external CRM connector factories."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .base import CrmConnectionConfig, CrmConnector


class CrmRegistryError(ValueError):
    pass


CrmConnectorFactory = Callable[[CrmConnectionConfig], CrmConnector]


class CrmConnectorRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, CrmConnectorFactory] = {}

    @staticmethod
    def normalize_provider_type(provider_type: Any) -> str:
        value = str(provider_type or "").strip().lower()
        aliases = {
            "salesforce": "salesforce",
            "salesforce_crm": "salesforce",
            "dingtalk": "dingtalk_crm",
            "feishu": "feishu_crm",
        }
        return aliases.get(value, value)

    def register(self, provider_type: str, factory: CrmConnectorFactory, *, replace: bool = False) -> CrmConnectorFactory:
        key = self.normalize_provider_type(provider_type)
        if not key or not callable(factory):
            raise CrmRegistryError("CRM provider requires a provider type and callable factory")
        if key in self._factories and not replace:
            raise CrmRegistryError(f"CRM provider already registered: {key}")
        self._factories[key] = factory
        return factory

    def unregister(self, provider_type: str) -> None:
        self._factories.pop(self.normalize_provider_type(provider_type), None)

    def get_factory(self, provider_type: str) -> CrmConnectorFactory:
        key = self.normalize_provider_type(provider_type)
        factory = self._factories.get(key)
        if factory is None:
            raise CrmRegistryError(f"CRM provider not registered: {key or '<empty>'}")
        return factory

    def build(self, config: CrmConnectionConfig) -> CrmConnector:
        return self.get_factory(config.provider_type)(config)

    def list_provider_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))


crm_connector_registry = CrmConnectorRegistry()
