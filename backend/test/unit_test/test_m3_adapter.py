from __future__ import annotations

import pytest

from integrations.m3.adapter import M3LookupAdapter


class StubM3Client:
    def __init__(self, response):
        self.response = response
        self.calls: list[dict[str, str]] = []

    async def lookup_shipment(self, *, query: str, customer_code: str):
        self.calls.append({"query": query, "customer_code": customer_code})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.mark.asyncio
async def test_lookup_normalizes_query_passes_customer_scope_and_returns_allowlisted_evidence():
    client = StubM3Client({
        "records": [{
            "CustomerCode": "ENT-001",
            "BillNo": "bl-123",
            "VesselVoyage": "EVER GIVEN / 118E",
            "ETA": "2026-09-24T08:00:00+08:00",
            "CurrentMilestone": "已离港",
            "InternalCost": "should never be exposed",
        }],
    })
    adapter = M3LookupAdapter(client=client)

    result = await adapter.lookup(query="  bl-123  ", customer_code="ENT-001")

    assert result.status == "found"
    assert result.query == "BL-123"
    assert client.calls == [{"query": "BL-123", "customer_code": "ENT-001"}]
    assert {item["label"] for item in result.evidence} == {
        "订单号", "提单号", "箱号", "船名 / 航次", "预计抵港", "当前节点", "实际抵港",
    }
    assert all("InternalCost" not in item for item in result.evidence)
    bill = next(item for item in result.evidence if item["label"] == "提单号")
    assert bill["value"] == "bl-123"
    assert bill["known"] is True


@pytest.mark.asyncio
async def test_lookup_hides_records_from_another_enterprise():
    client = StubM3Client({
        "items": [{"CustomerCode": "ENT-OTHER", "BillNo": "BL-123"}],
    })
    result = await M3LookupAdapter(client=client).lookup(query="BL-123", customer_code="ENT-001")

    assert result.status == "not_found"
    assert result.audit_outcome == "access_denied"
    assert result.evidence == []
    assert "其他企业" in result.summary


@pytest.mark.asyncio
async def test_lookup_requires_clarification_for_multiple_authorized_records():
    client = StubM3Client({
        "data": [
            {"CustomerCode": "ENT-001", "BillNo": "BL-123-A"},
            {"CustomerCode": "ENT-001", "BillNo": "BL-123-B"},
        ],
    })

    result = await M3LookupAdapter(client=client).lookup(query="BL-123", customer_code="ENT-001")

    assert result.status == "needs_clarification"
    assert result.audit_outcome == "multiple_matches"
    assert result.evidence == []


@pytest.mark.asyncio
async def test_lookup_maps_upstream_error_without_leaking_provider_details():
    client = StubM3Client(RuntimeError("secret provider response"))

    result = await M3LookupAdapter(client=client).lookup(query="BL-123", customer_code="ENT-001")

    assert result.status == "upstream_error"
    assert result.audit_outcome == "upstream_error"
    assert "secret provider response" not in result.summary
    assert result.evidence == []


@pytest.mark.asyncio
async def test_lookup_rejects_invalid_query_and_unconfigured_provider():
    invalid = await M3LookupAdapter(client=StubM3Client([])).lookup(query="", customer_code="ENT-001")
    assert invalid.status == "needs_clarification"

    unconfigured = await M3LookupAdapter().lookup(query="BL-123", customer_code="ENT-001")
    assert unconfigured.status == "upstream_error"


@pytest.mark.asyncio
async def test_lookup_does_not_accept_empty_customer_scope():
    with pytest.raises(ValueError, match="customer_code"):
        await M3LookupAdapter(client=StubM3Client([])).lookup(query="BL-123", customer_code="")


@pytest.mark.asyncio
async def test_fixed_mock_scope_unknown_and_section_contracts():
    adapter = M3LookupAdapter(use_mock=True)
    for query in ("MOCK-BL-A001", "MOCK-CONT-A001", "MOCK-ORDER-A001"):
        result = await adapter.lookup(query=query, customer_code="MOCK-ENT-A")
        assert result.status == "found"
        assert "模拟数据" in result.summary
    foreign = await adapter.lookup(query="MOCK-BL-B001", customer_code="MOCK-ENT-A")
    missing = await adapter.lookup(query="DOES-NOT-EXIST", customer_code="MOCK-ENT-A")
    assert (foreign.status, foreign.evidence, foreign.summary) == (missing.status, missing.evidence, missing.summary)
    schedule = await adapter.schedule(query="MOCK-BL-A001", customer_code="MOCK-ENT-A")
    assert {i["label"] for i in schedule.evidence} == {"船名 / 航次", "预计抵港"}
    milestones = await adapter.milestones(query="MOCK-BL-B001", customer_code="MOCK-ENT-B")
    assert all(not i["known"] and i["value"] == "暂无数据" for i in milestones.evidence)
    unowned = M3LookupAdapter(use_mock=True, mock_records=[{"BillNo": "UNOWNED"}])
    assert (await unowned.lookup(query="UNOWNED", customer_code="MOCK-ENT-A")).status == "not_found"
