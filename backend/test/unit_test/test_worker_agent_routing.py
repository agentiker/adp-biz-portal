"""Business workers always defer application selection to the database."""
import pytest


@pytest.mark.parametrize("mock", [True, False])
def test_bootstrap_does_not_use_env_app_or_local_m3(monkeypatch, mock):
    from test.app_bootstrap import ensure_app
    ensure_app()
    from config import tagentic_config
    from app_factory import TAgenticApp
    import worker
    monkeypatch.setattr(tagentic_config, "APP_CONFIGS", [{"ApplicationId": "old-env-app"}])
    monkeypatch.setattr(tagentic_config, "ADP_AGENT_CONFIGS", [{"agentId": "old", "applicationId": "old-env-app"}])
    monkeypatch.setattr(tagentic_config, "M3_USE_MOCK", mock)
    monkeypatch.setattr(TAgenticApp, "apps", {"old-env-app": object()})
    assert worker.build_agent_provider() is None
