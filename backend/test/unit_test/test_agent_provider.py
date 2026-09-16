from __future__ import annotations

from dataclasses import replace

import pytest

from core.delivery import DeliveryRetryableError
from integrations.adp.provider import (
    ADPAgentProvider,
    AgentRequest,
    AgentResponse,
    ControlledLookupAgentProvider,
)


def _request() -> AgentRequest:
    return AgentRequest(
        agent_id="platform-default",
        conversation_id="conv-42",
        run_id="run-42",
        channel="web",
        query=" BL-42 ",
        customer_code="ENT-001",
        trace_id="trace-42",
        visitor_id="platform:enterprise-42:account-42",
        corp_id="enterprise-42",
        corp_user_id="user-42",
    )


@pytest.mark.asyncio
async def test_controlled_provider_returns_platform_dto_and_drops_raw_fields():
    calls: list[dict[str, str]] = []

    class Adapter:
        async def lookup(self, *, query: str, customer_code: str):
            calls.append({"query": query, "customer_code": customer_code})
            return {
                "status": "found",
                "title": "已找到",
                "summary": "结果已校验",
                "traceId": "provider-trace",
                "evidence": [
                    {"label": "提单号", "value": "BL-42", "known": True},
                    {"label": "提单号", "value": "duplicate", "known": True},
                ],
                "providerSecret": "must-not-cross-boundary",
            }

    response = await ControlledLookupAgentProvider(Adapter()).execute(_request())

    assert calls == [{"query": "BL-42", "customer_code": "ENT-001"}]
    assert isinstance(response, AgentResponse)
    assert response.status == "found"
    assert response.query == "BL-42"
    assert response.provider_trace_id == "provider-trace"
    assert response.to_dict() == {
        "status": "found",
        "query": "BL-42",
        "title": "已找到",
        "summary": "结果已校验",
        "evidence": [{"label": "提单号", "value": "BL-42", "source": "平台受控工具", "capturedAt": "", "known": True}],
        "traceId": "provider-trace",
        "auditOutcome": "found",
    }
    assert "providerSecret" not in response.to_dict()
    assert ControlledLookupAgentProvider(Adapter()).capabilities == frozenset({"shipment.lookup"})


@pytest.mark.asyncio
async def test_controlled_provider_unconfigured_failure_is_explicit_upstream_error():
    class Adapter:
        async def lookup(self, *, query: str, customer_code: str):
            raise RuntimeError("provider credentials must not leak")

    response = await ControlledLookupAgentProvider(Adapter()).execute(_request())

    assert response.status == "upstream_error"
    assert response.audit_outcome == "upstream_error"
    assert "provider credentials" not in response.summary
    assert response.evidence == []


@pytest.mark.asyncio
async def test_controlled_provider_preserves_retryable_upstream_failures():
    class Adapter:
        async def lookup(self, *, query: str, customer_code: str):
            raise DeliveryRetryableError("provider_timeout")

    with pytest.raises(DeliveryRetryableError, match="provider_timeout"):
        await ControlledLookupAgentProvider(Adapter()).execute(_request())


@pytest.mark.asyncio
async def test_adp_provider_accumulates_text_and_allowlists_evidence():
    calls: list[dict] = []

    class Vendor:
        async def chat(self, **kwargs):
            calls.append(kwargs)
            yield b'data: {"Type":"response.created","RequestId":"req-42"}\n\n'
            yield (
                'data: {"Type":"text.delta","Text":"已找到 "}\n\n'
                'data: {"Type":"unknown.internal","Secret":"drop-me"}\n\n'
            ).encode()
            yield (
                'data: {"Type":"text.delta","Text":"船期信息",'
                '"Evidence":[{"Label":"船名","Value":"Evergreen","Source":"M3",'
                '"Known":true,"Secret":"drop-me"}]}\n\n'
            ).encode()

    response = await ADPAgentProvider(
        agent_id="shipment-agent", application_id="app-42", vendor=Vendor()
    ).execute(replace(_request(), agent_id="shipment-agent"))

    assert response.status == "completed"
    assert response.summary == "已找到 船期信息"
    assert response.provider_trace_id == "req-42"
    assert response.evidence == [{
        "label": "船名", "value": "Evergreen", "source": "M3", "capturedAt": "", "known": True,
    }]
    assert calls[0]["account_id"] == "platform:enterprise-42:account-42"
    assert calls[0]["contents"] == [{"Type": "text", "Text": "BL-42"}]


@pytest.mark.asyncio
async def test_adp_provider_splits_thought_from_reply():
    """Reasoning (thought message) must stream separately and stay out of the answer."""

    class Vendor:
        async def chat(self, **kwargs):
            # A thought message streams first, then the reply message.
            yield b'data: {"Type":"message.added","Message":{"MessageId":"m-t","Type":"thought"}}\n\n'
            yield 'data: {"Type":"text.delta","MessageId":"m-t","Text":"先分析提单"}\n\n'.encode()
            yield b'data: {"Type":"message.added","Message":{"MessageId":"m-r","Type":"reply"}}\n\n'
            yield 'data: {"Type":"text.delta","MessageId":"m-r","Text":"已到港。"}\n\n'.encode()

    class Sink:
        def __init__(self):
            self.answer = ""
            self.reasoning = ""
            self.closed = False

        async def emit(self, text):
            self.answer += text

        async def emit_reasoning(self, text):
            self.reasoning += text

        async def close(self):
            self.closed = True

    sink = Sink()
    response = await ADPAgentProvider(
        agent_id="shipment-agent", application_id="app-42", vendor=Vendor()
    ).execute(replace(_request(), agent_id="shipment-agent"), sink=sink)

    # The stored answer is the reply only; the thought never leaks into it.
    assert response.summary == "已到港。"
    assert "先分析提单" not in response.summary
    # The sink saw them on separate channels.
    assert sink.answer == "已到港。"
    assert sink.reasoning == "先分析提单"
    assert sink.closed is True


@pytest.mark.asyncio
async def test_adp_provider_error_and_missing_mapping_fail_closed():
    class ErrorVendor:
        async def chat(self, **_kwargs):
            yield b'data: {"Type":"unknown.internal","Error":"secret-token"}\n\n'
            yield b'data: {"Type":"error","Message":"AppKey=secret-token"}\n\n'

    response = await ADPAgentProvider(
        agent_id="shipment-agent", application_id="app-42", vendor=ErrorVendor()
    ).execute(replace(_request(), agent_id="shipment-agent"))
    assert response.status == "upstream_error"
    assert response.evidence == []
    assert "secret-token" not in response.summary

    missing = await ADPAgentProvider(
        agent_id="shipment-agent", application_id="app-42", vendor=None
    ).execute(replace(_request(), agent_id="shipment-agent"))
    assert missing.status == "upstream_error"


@pytest.mark.asyncio
async def test_adp_provider_vendor_exception_does_not_leak_error():
    class BrokenVendor:
        async def chat(self, **_kwargs):
            raise RuntimeError("AppKey=secret-token")
            yield b"never"

    response = await ADPAgentProvider(
        agent_id="shipment-agent", application_id="app-42", vendor=BrokenVendor()
    ).execute(replace(_request(), agent_id="shipment-agent"))
    assert response.status == "upstream_error"
    assert "secret-token" not in response.summary


@pytest.mark.asyncio
async def test_business_context_only_in_hidden_variables_and_never_streamed():
    calls = []
    class Vendor:
        async def chat(self, **kwargs):
            calls.append(kwargs)
            yield b'data: {"Type":"text.delta","Text":"unverified"}\n\n'
    class Sink:
        async def emit(self, text):
            pytest.fail("unverified business text was streamed")
        async def close(self):
            pass
    request = replace(_request(), context_token="pct_fixture_private_token")
    await ADPAgentProvider(agent_id=request.agent_id, application_id="app-test", vendor=Vendor()).execute(request, sink=Sink())
    assert request.context_token not in repr(request)
    assert request.context_token not in str(calls[0]["contents"])
    assert calls[0]["custom_variables"]["platform_context_token"] == request.context_token
    assert calls[0]["custom_variables"]["platform_run_id"] == request.run_id
    assert calls[0]["custom_variables"]["corp_id"] == request.corp_id
    assert calls[0]["custom_variables"]["corp_user_id"] == request.corp_user_id
