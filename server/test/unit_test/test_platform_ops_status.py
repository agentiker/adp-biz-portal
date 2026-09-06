from __future__ import annotations

import json
import importlib
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture(scope="module")
def platform_router():
    from app_factory import create_app_with_configs

    create_app_with_configs()
    return importlib.import_module("router.platform")


class Result:
    def __init__(self, *, scalar=None, rows=None):
        self.scalar = scalar
        self.rows = rows or []

    def scalar_one_or_none(self):
        return self.scalar

    def all(self):
        return self.rows


def test_error_category_uses_fixed_non_sensitive_values(platform_router):
    categorize = platform_router._error_category

    assert categorize("authorization_revoked: token=secret") == "authorization"
    assert categorize("upstream timeout while calling M3") == "timeout"
    assert categorize("database password=should-not-return") == "database"
    assert categorize("unexpected private payload") == "other"
    assert categorize(None) == "unknown"


def test_ops_suggestions_cover_blocked_delivery_and_schema(platform_router):
    suggestions = platform_router._ops_suggestions(
        schema_revision=6,
        delivery_counts={"uncertain": 1, "failed": 2, "queued": 3},
        run_counts={"upstream_error": 1},
        metadata={"status": "degraded"},
        expected_revision=7,
    )

    assert [item["code"] for item in suggestions] == [
        "schema_not_ready",
        "adp_metadata_degraded",
        "delivery_uncertain",
        "delivery_failed",
        "delivery_backlog",
        "execution_errors",
    ]
    assert all(set(item) == {"code", "message"} for item in suggestions)


@pytest.mark.asyncio
async def test_load_ops_status_returns_aggregate_fields_only(platform_router, monkeypatch):
    seen_at = datetime(2026, 9, 6, 3, 4, 5, tzinfo=timezone.utc)
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                Result(scalar=7),
                Result(rows=[("queued", 2), ("uncertain", 1)]),
                Result(rows=[("succeeded", 4), ("upstream_error", 1)]),
                Result(rows=[("shipment.lookup", "provider timeout", 1, seen_at)]),
            ]
        )
    )
    request = SimpleNamespace(ctx=SimpleNamespace(db=db))
    monkeypatch.setattr(
        platform_router,
        "_metadata_status_summary",
        lambda: {
            "status": "healthy",
            "configuredApplications": 1,
            "healthyApplications": 1,
            "degradedApplications": 0,
            "lastFailureAt": None,
        },
    )

    payload, status = await platform_router._load_ops_status(request)

    assert status == 200
    assert payload["delivery"] == {"byStatus": {"queued": 2, "uncertain": 1}}
    assert payload["executions"] == {"byStatus": {"succeeded": 4, "upstream_error": 1}}
    assert payload["recentFailures"] == [{
        "action": "shipment.lookup",
        "outcome": "timeout",
        "count": 1,
        "lastSeenAt": seen_at.isoformat(),
    }]
    serialized = json.dumps(payload, ensure_ascii=False)
    for sensitive_key in ("Payload", "Body", "Evidence", "Token", "Secret", "LastError"):
        assert sensitive_key not in serialized
    assert "provider timeout" not in serialized


@pytest.mark.asyncio
async def test_load_ops_status_hides_database_error(platform_router):
    db = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("postgres password=do-not-leak")))
    request = SimpleNamespace(ctx=SimpleNamespace(db=db))

    payload, status = await platform_router._load_ops_status(request)

    assert status == 503
    assert payload["database"] == {"status": "error", "reason": "RuntimeError"}
    assert payload["suggestions"] == [{
        "code": "ops_query_failed",
        "message": "状态聚合查询失败；检查数据库就绪状态和服务日志中的错误分类。",
    }]
    assert "do-not-leak" not in json.dumps(payload)


@pytest.mark.asyncio
async def test_ops_status_requires_diagnose_permission(platform_router, monkeypatch):
    request = SimpleNamespace(ctx=SimpleNamespace(platform=SimpleNamespace(permissions=frozenset())))
    view = platform_router.OpsStatusApi.get.__wrapped__

    with pytest.raises(platform_router.PlatformForbidden):
        await view(platform_router.OpsStatusApi(), request)

    request.ctx.platform.permissions = frozenset({"platform.diagnose"})
    monkeypatch.setattr(
        platform_router,
        "_load_ops_status",
        AsyncMock(return_value=({"status": "ok"}, 200)),
    )
    response = await view(platform_router.OpsStatusApi(), request)

    assert response.status == 200
    assert json.loads(response.body) == {"status": "ok"}
