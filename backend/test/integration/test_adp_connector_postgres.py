"""Isolated DB -> ADP SSE double -> real HTTP callback -> M3 -> durable reply."""
import json
import uuid

import pytest
from cryptography.fernet import Fernet
from sanic import Sanic
from sanic.response import json as json_response
from sqlalchemy import select

from test.integration.test_platform_worker_postgres import platform_sessionmaker, _seed_inbound
from core.delivery import DeliveryWorker
from core.platform_worker import build_platform_delivery_handlers, PLATFORM_REPLY_TASK_TYPE
from model.platform import PlatformEnterprise, PlatformToolDefinition, PlatformDeliveryTask, PlatformExecutionContext


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["found", "foreign", "missing", "no_callback", "conflict"])
async def test_database_app_connector_roundtrip(platform_sessionmaker, monkeypatch, mode):
    from test.app_bootstrap import ensure_app
    ensure_app()
    from config import tagentic_config
    from app_factory import TAgenticApp
    from router.platform import AdpShipmentLookupApi, AdpShipmentScheduleApi, AdpShipmentMilestonesApi
    from core.error import BaseError
    from core.adp_app import create_adp_app
    from integrations.adp import registry
    monkeypatch.setattr(tagentic_config, "PLATFORM_CHANNEL_CREDENTIAL_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(tagentic_config, "ADP_TOOL_SERVICE_TOKEN", "test-service-token")
    monkeypatch.setattr(tagentic_config, "M3_USE_MOCK", True)
    app = Sanic(f"connector_test_{uuid.uuid4().hex}")
    for operation, view in (("lookup", AdpShipmentLookupApi), ("schedule", AdpShipmentScheduleApi), ("milestones", AdpShipmentMilestonesApi)):
        app.add_route(view.as_view(), f"/api/internal/adp/tools/shipment/{operation}")

    @app.middleware("request")
    async def session(request):
        request.ctx.db = platform_sessionmaker()

    @app.middleware("response")
    async def close(request, response):
        await request.ctx.db.rollback()
        await request.ctx.db.close()

    @app.exception(BaseError)
    async def expected_error(request, exc):
        return json_response({"error": "rejected"}, status=exc.status_code)

    headers_used = {}
    responses = []
    async def callback(operation, headers, body):
        _, response = await app.asgi_client.post(f"/api/internal/adp/tools/shipment/{operation}", headers=headers, json=body)
        return response

    class Vendor:
        def __init__(self, config, application_id):
            pass
        async def chat(self, **kwargs):
            variables = kwargs["custom_variables"]
            headers = {"X-ADP-Service-Token": "test-service-token", "X-Platform-Context-Token": variables["platform_context_token"],
                       "X-ADP-Request-Id": variables["platform_tool_request_id"] + ":lookup"}
            headers_used.update(headers)
            query = {"foreign": "MOCK-BL-B001", "missing": "ABSENT"}.get(mode, "MOCK-BL-A001")
            body = {"query": query, "runId": variables["platform_run_id"], "conversationId": variables["platform_conversation_id"], "agentId": variables["platform_agent_id"]}
            assert (await callback("lookup", {**headers, "X-ADP-Service-Token": "wrong"}, body)).status == 401
            assert (await callback("lookup", {**headers, "X-Platform-Context-Token": "pct_wrong"}, body)).status == 401
            assert (await callback("lookup", headers, {**body, "runId": "foreign-run"})).status == 403
            assert (await callback("lookup", headers, {**body, "customerCode": "MOCK-ENT-B"})).status == 400
            assert (await callback("lookup", headers, {**body, "query": "X" * 129})).status == 400
            assert (await callback("lookup", {**headers, "X-ADP-Request-Id": "X" * 129}, body)).status == 400
            if mode != "no_callback":
                response = await callback("lookup", headers, body)
                assert response.status == 200
                responses.append(response.json)
                assert (await callback("lookup", headers, body)).status == 403
                if mode in ("found", "conflict"):
                    for operation in ("schedule", "milestones"):
                        response = await callback(operation, {**headers, "X-ADP-Request-Id": variables["platform_tool_request_id"] + ":" + operation}, {**body, "query": "MOCK-CONT-A001"} if mode == "conflict" else body)
                        assert response.status == 200
            # Deliberately fabricated provider evidence/text must not reach the reply.
            yield b'data: {"Type":"text.delta","Text":"FABRICATED ARRIVAL", "Evidence":[{"Label":"ETA","Value":"FAKE"}]}\n\n'

    monkeypatch.setitem(TAgenticApp.vendors, "connector-test", Vendor)
    registry.clear_provider_cache()
    inbound_id, task_id = await _seed_inbound(platform_sessionmaker)
    async with platform_sessionmaker() as db:
        enterprise = (await db.execute(select(PlatformEnterprise))).scalar_one()
        enterprise.CustomerCode = "MOCK-ENT-A"
        await create_adp_app(db, name="Test", application_id="APP-TEST", vendor="connector-test", app_key="test-key",
                             secret_id="test-id", secret_key="test-secret", secret_app_id="test-app", is_default=True)
        for operation in ("schedule", "milestones"):
            db.add(PlatformToolDefinition(Name=f"shipment.{operation}", Version="1", Permission="shipment.read", Enabled=True, ReadOnly=True))
        await db.commit()
    worker = DeliveryWorker(sessionmaker=platform_sessionmaker, handlers=build_platform_delivery_handlers(platform_sessionmaker), worker_id="connector-test")
    assert await worker.run_once()
    async with platform_sessionmaker() as db:
        task = await db.get(PlatformDeliveryTask, task_id)
        assert task.Status == "succeeded", task.LastError
        reply = (await db.execute(select(PlatformDeliveryTask).where(PlatformDeliveryTask.TaskType == PLATFORM_REPLY_TASK_TYPE))).scalar_one()
        serialized = json.dumps(reply.Payload, ensure_ascii=False)
        assert "FABRICATED" not in serialized and "FAKE" not in serialized
        assert headers_used["X-Platform-Context-Token"] not in serialized
        assert reply.Payload["status"] == {"found": "found", "conflict": "needs_clarification", "no_callback": "upstream_error"}.get(mode, "not_found")
        if mode == "found":
            assert "模拟数据" in serialized and "ALPHA" in serialized
        else:
            assert "BETA" not in serialized
        contexts = list((await db.execute(select(PlatformExecutionContext))).scalars())
        assert all(context.RevokedAt for context in contexts)
    assert (await callback("lookup", {**headers_used, "X-ADP-Request-Id": "late-request"}, {"query": "MOCK-BL-A001"})).status == 401
    assert await worker.run_once()
    async with platform_sessionmaker() as db:
        persisted_reply = await db.get(PlatformDeliveryTask, reply.Id)
        assert persisted_reply.Status == "succeeded"
    registry.clear_provider_cache()
