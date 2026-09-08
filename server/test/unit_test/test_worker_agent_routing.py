"""Provider selection: a channel message must reach the ADP application.

Whether the agent can query M3 is the agent's own tool configuration. The
gateway's job is identity, authorization, evidence and audit — so a missing M3
setting must never keep a message from reaching ADP, and a missing ADP
application must never be answered by a local stand-in.
"""

from __future__ import annotations

import pytest

from integrations.adp.provider import ADPAgentProvider, ControlledLookupAgentProvider


class _Vendor:
    def chat(self, **_kwargs):  # pragma: no cover - only needs to be callable
        return iter(())


@pytest.fixture
def worker_module():
    from test.app_bootstrap import ensure_app

    ensure_app()
    import importlib

    return importlib.import_module("worker")


def _configure(monkeypatch, worker_module, **overrides):
    from app_factory import TAgenticApp

    defaults = {
        "ADP_AGENT_CONFIGS": [],
        "ADP_DEFAULT_AGENT_ID": "",
        "APP_CONFIGS": [],
        "M3_USE_MOCK": False,
        "M3_BASE_URL": "",
        "M3_TIMEOUT_SECONDS": 10,
    }
    defaults.update(overrides)
    for key, value in defaults.items():
        monkeypatch.setattr(worker_module.tagentic_config, key, value, raising=False)
    monkeypatch.setattr(TAgenticApp, "apps", overrides.pop("_apps", {}), raising=False)


def test_single_app_config_routes_to_the_platform_adp_application(monkeypatch, worker_module):
    from app_factory import TAgenticApp

    vendor = _Vendor()
    _configure(monkeypatch, worker_module, APP_CONFIGS=[{"ApplicationId": "app-1", "Vendor": "Tencent"}])
    monkeypatch.setattr(TAgenticApp, "apps", {"app-1": vendor}, raising=False)

    provider = worker_module.build_agent_provider()

    assert isinstance(provider, ADPAgentProvider)
    assert provider.application_id == "app-1"
    assert provider.vendor is vendor
    assert provider.agent_id == "platform-default"


def test_missing_m3_config_does_not_stop_routing_to_adp(monkeypatch, worker_module):
    """The regression this test exists for: M3 was gating the whole message."""
    from app_factory import TAgenticApp

    _configure(monkeypatch, worker_module, APP_CONFIGS=[{"ApplicationId": "app-1"}])
    monkeypatch.setattr(TAgenticApp, "apps", {"app-1": _Vendor()}, raising=False)

    provider = worker_module.build_agent_provider()

    # Previously this fell through to a local M3 provider and then failed with
    # "M3 upstream is not configured", never reaching ADP at all.
    assert isinstance(provider, ADPAgentProvider)
    assert not isinstance(provider, ControlledLookupAgentProvider)


def test_default_agent_id_is_honored(monkeypatch, worker_module):
    from app_factory import TAgenticApp

    _configure(
        monkeypatch,
        worker_module,
        APP_CONFIGS=[{"ApplicationId": "app-1"}],
        ADP_DEFAULT_AGENT_ID="freight-agent",
    )
    monkeypatch.setattr(TAgenticApp, "apps", {"app-1": _Vendor()}, raising=False)

    provider = worker_module.build_agent_provider()
    assert provider.agent_id == "freight-agent"


def test_several_applications_without_a_mapping_fail_closed(monkeypatch, worker_module):
    from app_factory import TAgenticApp

    _configure(
        monkeypatch,
        worker_module,
        APP_CONFIGS=[{"ApplicationId": "app-1"}, {"ApplicationId": "app-2"}],
    )
    monkeypatch.setattr(TAgenticApp, "apps", {"app-1": _Vendor(), "app-2": _Vendor()}, raising=False)

    provider = worker_module.build_agent_provider()

    # Guessing which application serves customers would answer with the wrong
    # agent, so no vendor is attached and each message reports upstream error.
    assert isinstance(provider, ADPAgentProvider)
    assert provider.vendor is None


def test_unusable_configured_application_reports_upstream_instead_of_local_fallback(
    monkeypatch, worker_module
):
    from app_factory import TAgenticApp

    _configure(monkeypatch, worker_module, APP_CONFIGS=[{"ApplicationId": "app-1"}])
    monkeypatch.setattr(TAgenticApp, "apps", {}, raising=False)

    provider = worker_module.build_agent_provider()
    assert isinstance(provider, ADPAgentProvider)
    assert provider.application_id == "app-1"
    assert provider.vendor is None


def test_local_m3_provider_only_when_m3_is_configured_on_purpose(monkeypatch, worker_module):
    from app_factory import TAgenticApp

    _configure(monkeypatch, worker_module, M3_USE_MOCK=True)
    monkeypatch.setattr(TAgenticApp, "apps", {}, raising=False)

    provider = worker_module.build_agent_provider()
    assert isinstance(provider, ControlledLookupAgentProvider)


def test_nothing_configured_fails_honestly(monkeypatch, worker_module):
    from app_factory import TAgenticApp

    _configure(monkeypatch, worker_module)
    monkeypatch.setattr(TAgenticApp, "apps", {}, raising=False)

    provider = worker_module.build_agent_provider()
    assert isinstance(provider, ADPAgentProvider)
    assert provider.vendor is None
    assert provider.application_id == ""


def test_explicit_agent_mapping_still_wins(monkeypatch, worker_module):
    from app_factory import TAgenticApp

    vendor = _Vendor()
    _configure(
        monkeypatch,
        worker_module,
        ADP_AGENT_CONFIGS=[{"agentId": "mapped", "applicationId": "app-9"}],
        APP_CONFIGS=[{"ApplicationId": "app-1"}],
    )
    monkeypatch.setattr(TAgenticApp, "apps", {"app-9": vendor, "app-1": _Vendor()}, raising=False)

    provider = worker_module.build_agent_provider()
    assert provider.agent_id == "mapped"
    assert provider.application_id == "app-9"
