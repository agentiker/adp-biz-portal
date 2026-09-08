from types import SimpleNamespace
import json

import pytest

from test.app_bootstrap import ensure_app


# Importing the route after app creation registers it on a Sanic application.
ensure_app()
from router.health import healthz, readyz  # noqa: E402
import router.health as health_module  # noqa: E402


@pytest.mark.asyncio
async def test_healthz_is_independent_from_database():
    result = await healthz(None)

    assert result.status == 200
    assert json.loads(result.body) == {"status": "ok", "service": "api"}


@pytest.mark.asyncio
async def test_readyz_checks_database_and_schema(monkeypatch):
    class FakeDb:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def execute(self, statement):
            assert str(statement) == "SELECT 1"

    validated = False

    async def validate_startup(_db):
        nonlocal validated
        validated = True

    monkeypatch.setattr(health_module.Migration, "validate_startup", validate_startup)
    request = SimpleNamespace(app=SimpleNamespace(config={"sessionmaker": FakeDb}))

    result = await readyz(request)

    assert result.status == 200
    payload = json.loads(result.body)
    assert payload["status"] == "ready"
    assert payload["schemaRevision"] == health_module.Migration.CURRENT_PLATFORM_SCHEMA_VERSION
    assert validated is True


@pytest.mark.asyncio
async def test_readyz_hides_database_error_details():
    class BrokenDb:
        async def __aenter__(self):
            raise RuntimeError("postgres password=do-not-leak")

        async def __aexit__(self, *_):
            return False

    request = SimpleNamespace(app=SimpleNamespace(config={"sessionmaker": BrokenDb}))

    result = await readyz(request)

    assert result.status == 503
    assert json.loads(result.body) == {"status": "not_ready", "reason": "RuntimeError"}
