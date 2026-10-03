"""Provider-neutral contracts for synchronizing an external CRM.

CRM records are imported into the platform and linked to canonical platform
users, enterprises, and memberships. A connector never decides authorization;
the platform execution context remains the source of truth for that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class CrmCapabilities:
    list_organizations: bool = False
    list_users: bool = False
    resolve_identity: bool = False
    pull_changes: bool = False
    webhook: bool = False


@dataclass(frozen=True, slots=True)
class CrmConnectionConfig:
    provider_type: str
    tenant_id: str
    credentials: Mapping[str, Any] = field(default_factory=dict, repr=False)
    settings: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CrmHealth:
    healthy: bool
    provider_type: str
    message: str = ""


@dataclass(frozen=True, slots=True)
class ExternalOrganization:
    external_id: str
    name: str
    status: str = "active"
    attributes: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExternalUser:
    external_id: str
    display_name: str
    organization_id: str
    status: str = "active"
    attributes: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExternalPrincipal:
    external_tenant_id: str
    external_user_id: str
    external_organization_id: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OrganizationPage:
    items: tuple[ExternalOrganization, ...] = ()
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class UserPage:
    items: tuple[ExternalUser, ...] = ()
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class ChangePage:
    changes: tuple[Mapping[str, Any], ...] = ()
    next_cursor: str | None = None


@runtime_checkable
class CrmConnector(Protocol):
    """Async connector implemented by one CRM vendor adapter."""

    @property
    def capabilities(self) -> CrmCapabilities: ...

    async def validate_config(self, config: CrmConnectionConfig) -> None: ...

    async def health_check(self) -> CrmHealth: ...

    async def list_organizations(self, cursor: str | None = None) -> OrganizationPage: ...

    async def list_users(self, external_org_id: str, cursor: str | None = None) -> UserPage: ...

    async def resolve_identity(
        self,
        external_tenant_id: str,
        external_user_id: str,
    ) -> ExternalPrincipal | None: ...

    async def pull_changes(self, cursor: str | None = None) -> ChangePage: ...
