import pytest

from test.app_bootstrap import ensure_app

# Importing the middleware registers listeners against the current Sanic app.
ensure_app()
import middleware.application as application_module


class _Vendor:
    def __init__(self, application_id, *, failure=None):
        self.application_id = application_id
        self.config = {"Vendor": "Tencent"}
        self.failure = failure

    async def get_info(self):
        if self.failure is not None:
            raise self.failure
        return type("ApplicationInfo", (), {"ApplicationId": "stale"})()


class _AuditDb:
    def __init__(self):
        self.events = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    def add(self, event):
        self.events.append(event)

    async def commit(self):
        self.committed = True


class _FakeApp:
    def __init__(self, apps, db):
        self.apps = apps
        self.config = {"sessionmaker": lambda: db}


@pytest.mark.asyncio
async def test_metadata_failure_isolated_and_recorded_without_affecting_chat(monkeypatch):
    db = _AuditDb()
    fake_app = _FakeApp(
        {
            "healthy": _Vendor("healthy"),
            "broken": _Vendor("broken", failure=RuntimeError("AppKey=secret-value upstream timeout")),
        },
        db,
    )
    monkeypatch.setattr(application_module, "app", fake_app)
    application_module.CoreApplication._instance = None
    core = application_module.CoreApplication()

    await core.update_application_info()

    assert [item.ApplicationId for item in core.apps_info] == ["healthy"]
    assert core.metadata_status["healthy"]["status"] == "healthy"
    assert core.metadata_status["broken"]["status"] == "degraded"
    assert core.metadata_status["broken"]["chatStatus"] == "unchanged"
    assert len(db.events) == 1
    assert db.committed is True
    event = db.events[0]
    assert event.Action == "adp.metadata.refresh"
    assert event.TargetId == "broken"
    assert event.Outcome == "degraded"
    assert event.Metadata["fallback"] == "last_known_metadata_or_application_id"
    assert "secret-value" not in event.Metadata["errorMessage"]


@pytest.mark.asyncio
async def test_metadata_refresh_keeps_last_known_info_on_transient_failure(monkeypatch):
    db = _AuditDb()
    vendor = _Vendor("app-1")
    fake_app = _FakeApp({"app-1": vendor}, db)
    monkeypatch.setattr(application_module, "app", fake_app)
    application_module.CoreApplication._instance = None
    core = application_module.CoreApplication()

    await core.update_application_info()
    vendor.failure = OSError("metadata endpoint unavailable")
    await core.update_application_info()

    assert [item.ApplicationId for item in core.apps_info] == ["app-1"]
    assert core.metadata_status["app-1"]["status"] == "degraded"
