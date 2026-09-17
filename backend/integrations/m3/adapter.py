"""Controlled, read-only M3 shipment lookup.

The adapter deliberately owns the response contract. Callers cannot pass an
arbitrary customer code through the HTTP layer, and upstream fields are
reduced to a small evidence allow-list before they reach a user.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, Mapping

import aiohttp


class M3UpstreamError(RuntimeError):
    """Raised when the real M3 provider cannot be reached or parsed."""


@dataclass
class M3LookupResult:
    status: str
    query: str
    title: str
    summary: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    trace_id: str = field(default_factory=lambda: f"trc_m3_{uuid.uuid4().hex[:12]}")
    audit_outcome: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "query": self.query,
            "title": self.title,
            "summary": self.summary,
            "evidence": self.evidence,
            "traceId": self.trace_id,
        }


def _now_text() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _first(record: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _records(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    for key in ("records", "Records", "items", "Items", "shipments", "Shipments", "data", "Data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
        if isinstance(value, Mapping):
            nested = _records(value)
            if nested:
                return nested
    # A single shipment object is also accepted, but error envelopes are not.
    if not any(key in payload for key in ("Error", "error", "message", "Message")):
        return [payload]
    return []


def _customer_code(record: Mapping[str, Any]) -> str | None:
    value = _first(record, "customer_code", "CustomerCode", "customerCode", "Customer", "customer")
    return str(value).strip() if value not in (None, "") else None


def _query_matches(record: Mapping[str, Any], query: str) -> bool:
    query_upper = query.upper()
    if any(term in query_upper for term in ("近期", "最近", "我的订单", "订单列表", "MY ORDERS", "RECENT")):
        return True
    identifiers = [str(record[key]).upper() for key in (
        "query", "Query", "OrderNo", "order_no", "bill_no", "BillNo", "BLNo", "BlNo",
        "BillOfLading", "billOfLading", "container_no", "ContainerNo", "ContainerNumber",
        "containerNumber", "tracking_no", "TrackingNo", "Code",
    ) if record.get(key) not in (None, "")]
    return bool(identifiers) and any(query_upper in value for value in identifiers)


def _is_recent_query(query: str) -> bool:
    query_upper = query.upper()
    return any(term in query_upper for term in ("近期", "最近", "我的订单", "订单列表", "MY ORDERS", "RECENT"))


_EVIDENCE_FIELDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("订单号", "M3 / shipment.lookup", ("OrderNo", "order_no")),
    ("提单号", "M3 / shipment.lookup", ("bill_no", "BillNo", "BLNo", "BlNo", "BillOfLading", "billOfLading")),
    ("箱号", "M3 / shipment.lookup", ("container_no", "ContainerNo", "ContainerNumber", "containerNumber")),
    ("船名 / 航次", "M3 / shipment.schedule", ("vessel_voyage", "VesselVoyage", "Vessel", "vessel", "Voyage", "voyage")),
    ("预计抵港", "M3 / shipment.schedule", ("eta", "ETA", "EstimatedArrival", "estimatedArrival")),
    ("当前节点", "M3 / shipment.milestones", ("current_milestone", "CurrentMilestone", "Milestone", "milestone", "Status", "status")),
    ("实际抵港", "M3 / shipment.milestones", ("ata", "ATA", "ActualArrival", "actualArrival")),
)


def _evidence(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    captured = _now_text()
    output: list[dict[str, Any]] = []
    for label, source, keys in _EVIDENCE_FIELDS:
        value = _first(record, *keys)
        known = value not in (None, "", [], {})
        output.append({
            "label": label,
            "value": str(value) if known else "暂无数据",
            "source": source,
            "capturedAt": captured,
            "known": known,
        })
    return output


class M3LookupAdapter:
    def __init__(
        self,
        *,
        use_mock: bool = False,
        base_url: str = "",
        timeout_seconds: int = 10,
        client: Any = None,
        mock_records: list[Mapping[str, Any]] | None = None,
    ):
        self.use_mock = bool(use_mock)
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.client = client
        self.mock_records = mock_records

    async def _fetch(self, query: str, customer_code: str) -> Any:
        if self.client is not None:
            method = getattr(self.client, "lookup_shipment", None) or getattr(self.client, "lookup", None)
            if method is None and callable(self.client):
                method = self.client
            if method is None:
                raise M3UpstreamError("M3 client has no lookup method")
            try:
                result = method(query=query, customer_code=customer_code)
                if isinstance(result, Awaitable):
                    return await result
                return result
            except M3UpstreamError:
                raise
            except Exception as exc:
                # Provider-specific exceptions must not leak through the
                # stable adapter contract or reach the customer response.
                raise M3UpstreamError("M3 client request failed") from exc
        if not self.base_url:
            raise M3UpstreamError("M3 upstream is not configured")
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{self.base_url}/shipments/lookup",
                    json={"query": query, "customerCode": customer_code},
                ) as response:
                    if response.status >= 400:
                        raise M3UpstreamError(f"M3 returned HTTP {response.status}")
                    return await response.json()
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            raise M3UpstreamError("M3 request failed") from exc

    async def lookup(self, *, query: str, customer_code: str) -> M3LookupResult:
        normalized_query = str(query or "").strip().upper()
        allowed_customer = str(customer_code or "").strip()
        if not normalized_query or len(normalized_query) > 128:
            return M3LookupResult(
                status="needs_clarification",
                query=normalized_query,
                title="需要补充查询条件",
                summary="请输入有效的提单号或箱号。",
            )
        if not allowed_customer:
            raise ValueError("customer_code is required")

        if self.use_mock:
            records: Any = self.mock_records
            if records is None:
                from integrations.m3.mock import MOCK_RECORDS
                records = list(MOCK_RECORDS)

        else:
            try:
                records = await self._fetch(normalized_query, allowed_customer)
            except M3UpstreamError:
                return M3LookupResult(
                    status="upstream_error",
                    query=normalized_query,
                    title="M3 暂时无法响应",
                    summary="业务系统暂时不可用，请稍后重试。平台没有使用未核实的数据替代结果。",
                    audit_outcome="upstream_error",
                )
            if isinstance(records, Mapping) and any(k in records for k in ("Error", "error")):
                return M3LookupResult(
                    status="upstream_error",
                    query=normalized_query,
                    title="M3 暂时无法响应",
                    summary="业务系统返回了错误，平台没有使用未核实的数据替代结果。",
                    audit_outcome="upstream_error",
                )

        candidates = [
            record for record in _records(records)
            if (_customer_code(record) == allowed_customer) and _query_matches(record, normalized_query)
        ]
        denied = [record for record in _records(records) if _customer_code(record) not in (None, allowed_customer)]
        if len(candidates) > 1 and not _is_recent_query(normalized_query):
            return M3LookupResult(
                status="needs_clarification",
                query=normalized_query,
                title="找到多条可能的业务记录",
                summary="请补充更完整的提单号或箱号后重试。平台不会替你选择一条未经确认的记录。",
                audit_outcome="multiple_matches",
            )
        if not candidates:
            return M3LookupResult(
                status="not_found",
                query=normalized_query,
                title="未找到可访问的业务记录",
                summary="请检查提单号或箱号是否正确。如果记录属于其他企业，平台不会返回其存在性。",
                audit_outcome="access_denied" if denied else "not_found",
            )

        evidence: list[dict[str, Any]] = []
        for index, record in enumerate(candidates, start=1):
            record_evidence = _evidence(record)
            if len(candidates) > 1:
                for item in record_evidence:
                    item["label"] = f"订单 {index} · {item['label']}"
            if self.use_mock:
                for item in record_evidence:
                    item["source"] = item["source"].replace("M3 /", "M3 Mock /", 1)
            evidence.extend(record_evidence)
        count_text = f"找到 {len(candidates)} 条" if len(candidates) > 1 else "已找到 1 条"
        return M3LookupResult(
            status="found",
            query=normalized_query,
            title=f"{count_text}可访问记录",
            summary=("【模拟数据，仅供联调】" if self.use_mock else "") + f"以下结果来自当前企业授权范围，共 {len(candidates)} 条。未返回的字段表示 M3 暂无可核实数据。",
            evidence=evidence,
            audit_outcome="found",
        )

    async def schedule(self, *, query: str, customer_code: str) -> M3LookupResult:
        return await self._section(query=query, customer_code=customer_code, section="schedule")

    async def milestones(self, *, query: str, customer_code: str) -> M3LookupResult:
        return await self._section(query=query, customer_code=customer_code, section="milestones")

    async def _section(self, *, query: str, customer_code: str, section: str) -> M3LookupResult:
        # These are projections of the lookup contract, not invented upstream APIs.
        result = await self.lookup(query=query, customer_code=customer_code)
        result.evidence = [item for item in result.evidence if item["source"].endswith(f"shipment.{section}")]
        return result
