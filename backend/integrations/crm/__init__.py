"""External CRM connector contracts and registry."""

from .base import (
    ChangePage,
    CrmCapabilities,
    CrmConnectionConfig,
    CrmConnector,
    CrmHealth,
    ExternalOrganization,
    ExternalPrincipal,
    ExternalUser,
    OrganizationPage,
    UserPage,
)
from .registry import CrmConnectorRegistry, CrmRegistryError, crm_connector_registry

__all__ = [
    "ChangePage",
    "CrmCapabilities",
    "CrmConnectionConfig",
    "CrmConnector",
    "CrmHealth",
    "ExternalOrganization",
    "ExternalPrincipal",
    "ExternalUser",
    "OrganizationPage",
    "UserPage",
    "CrmConnector",
    "CrmConnectorRegistry",
    "CrmRegistryError",
    "crm_connector_registry",
]
