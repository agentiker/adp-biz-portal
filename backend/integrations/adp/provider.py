"""Stable Agent/ADP provider contracts used by platform orchestration.

The worker owns identity, authorization, execution context and persistence.
Providers receive a server-issued request envelope and return only the
platform response DTO.  Provider-specific response fields must not cross this
boundary.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from core.delivery import DeliveryRetryableError
from integrations.m3.adapter import M3LookupAdapter, M3LookupResult


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AgentRequest:
    """Provider input after the platform has validated identity and scope."""

    agent_id: str
    conversation_id: str
    run_id: str
    channel: str
    query: str
    customer_code: str
    trace_id: str
    visitor_id: str = ""
    context_token: str = field(default="", repr=False)


@dataclass(frozen=True, slots=True)
class AgentResponse:
    """Provider output that is safe for platform persistence and replies."""

    status: str
    query: str
    title: str
    summary: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    provider_trace_id: str = ""
    audit_outcome: str = "upstream_error"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "query": self.query,
            "title": self.title,
            "summary": self.summary,
            "evidence": self.evidence,
            "traceId": self.provider_trace_id,
            "auditOutcome": self.audit_outcome,
        }

    @classmethod
    def upstream_error(cls, query: str) -> "AgentResponse":
        return cls(
            status="upstream_error",
            query=query,
            title="业务系统暂时无法响应",
            summary="业务系统暂时不可用，请稍后重试。平台没有使用未核实的数据替代结果。",
            audit_outcome="upstream_error",
        )


class StreamSink(Protocol):
    """Receives agent text while it is still being produced."""

    async def emit(self, text: str) -> None:
        """Deliver one ready chunk of reply text to the channel."""


class AgentProvider(Protocol):
    """Application-facing Agent/ADP provider contract."""

    @property
    def capabilities(self) -> frozenset[str]:
        """Return provider capabilities in platform tool names."""

    async def execute(self, request: AgentRequest, *, sink: Any = None) -> AgentResponse:
        """Execute one server-scoped Agent request.

        ``sink`` is optional. When supplied, a provider that receives upstream
        text incrementally forwards it as it arrives so the customer sees the
        answer being written instead of waiting for the whole response.
        """


def allowlisted_evidence(raw: Any) -> list[dict[str, Any]]:
    """Reduce provider evidence to bounded, user-visible fields."""
    if not isinstance(raw, list):
        return []
    output: list[dict[str, Any]] = []
    labels: set[str] = set()
    for item in raw[:64]:
        if not isinstance(item, Mapping):
            continue
        label = item.get("label")
        if not isinstance(label, str) or not label.strip():
            continue
        normalized_label = label.strip()[:128]
        if normalized_label in labels:
            continue
        value = item.get("value")
        source = item.get("source")
        output.append(
            {
                "label": normalized_label,
                "value": str(value if value not in (None, "") else "暂无数据")[:4000],
                "source": str(source or "平台受控工具")[:255],
                "capturedAt": str(item.get("capturedAt") or "")[:64],
                "known": bool(item.get("known", False)),
            }
        )
        labels.add(normalized_label)
    return output


def normalize_agent_response(raw: Any, *, query: str) -> AgentResponse:
    """Map a provider result into the stable platform response DTO."""
    if isinstance(raw, AgentResponse):
        return AgentResponse(
            status=raw.status[:64] if isinstance(raw.status, str) and raw.status else "upstream_error",
            query=query,
            title=raw.title[:255] if isinstance(raw.title, str) and raw.title else "业务系统暂时无法响应",
            summary=raw.summary[:2000] if isinstance(raw.summary, str) and raw.summary else "业务系统暂时不可用，请稍后重试。平台没有使用未核实的数据替代结果。",
            evidence=allowlisted_evidence(raw.evidence),
            provider_trace_id=raw.provider_trace_id[:64] if isinstance(raw.provider_trace_id, str) else "",
            audit_outcome=raw.audit_outcome[:64] if isinstance(raw.audit_outcome, str) and raw.audit_outcome else "upstream_error",
        )

    if isinstance(raw, M3LookupResult):
        return AgentResponse(
            status=raw.status,
            query=query,
            title=raw.title,
            summary=raw.summary,
            evidence=allowlisted_evidence(raw.evidence),
            provider_trace_id=raw.trace_id,
            audit_outcome=raw.audit_outcome or raw.status,
        )

    if isinstance(raw, Mapping):
        status = raw.get("status")
        title = raw.get("title")
        summary = raw.get("summary")
        if not isinstance(status, str) or not status.strip():
            status = "upstream_error"
        if not isinstance(title, str) or not title.strip():
            title = "业务系统暂时无法响应"
        if not isinstance(summary, str) or not summary.strip():
            summary = "业务系统暂时不可用，请稍后重试。平台没有使用未核实的数据替代结果。"
        return AgentResponse(
            status=status.strip()[:64],
            query=query,
            title=title.strip()[:255],
            summary=summary.strip()[:2000],
            evidence=allowlisted_evidence(raw.get("evidence", [])),
            provider_trace_id=str(raw.get("traceId") or "")[:64],
            audit_outcome=str(raw.get("auditOutcome") or status).strip()[:64],
        )

    return AgentResponse.upstream_error(query)


class ControlledLookupAgentProvider:
    """Local provider that exposes the controlled M3 lookup as an Agent."""

    capabilities = frozenset({"shipment.lookup"})

    def __init__(self, lookup_adapter: Any = None):
        self.lookup_adapter = lookup_adapter or M3LookupAdapter()

    async def execute(self, request: AgentRequest, *, sink: Any = None) -> AgentResponse:
        # This local provider has no upstream stream to forward, so ``sink`` is
        # accepted for contract compatibility and deliberately unused.
        # The adapter receives only the server-selected customer scope. The
        # Agent envelope remains available for a future real ADP implementation
        # without making the worker depend on ADP's raw request shape.
        normalized_query = str(request.query or "").strip()
        try:
            raw = await self.lookup_adapter.lookup(
                query=normalized_query,
                customer_code=request.customer_code,
            )
        except DeliveryRetryableError:
            raise
        except Exception:
            return AgentResponse.upstream_error(normalized_query.upper())
        return normalize_agent_response(raw, query=normalized_query.upper())


class _ConversationCallback:
    """No-op callback used by the provider boundary.

    Platform conversations are persisted by the Worker.  ADP still requires
    a callback for its protocol, so this callback returns a transient object
    without writing vendor-owned conversation state to the database.
    """

    def __init__(self, *, conversation_id: str, application_id: str, title: str):
        self.conversation_id = conversation_id
        self.application_id = application_id
        self.title = title

    def _conversation(self):
        # Import lazily so the local M3 provider remains usable without
        # importing the legacy chat model during unit-only execution.
        from model.chat import ChatConversation

        return ChatConversation(
            Id=self.conversation_id,
            AccountId="00000000-0000-0000-0000-000000000000",
            ApplicationId=self.application_id,
            Title=self.title[:255] or "业务查询",
        )

    async def create(self, title: str = None, vendor_conversation_id: str = None):
        if vendor_conversation_id:
            self.conversation_id = str(vendor_conversation_id)
        if title:
            self.title = title
        return self._conversation()

    async def update(self, conversation_id: str = None, title: str = None, vendor_conversation_id: str = None):
        if conversation_id:
            self.conversation_id = str(conversation_id)
        if vendor_conversation_id:
            self.conversation_id = str(vendor_conversation_id)
        if title:
            self.title = title
        return self._conversation()


def _sse_payloads(raw: Any) -> list[dict[str, Any]]:
    """Decode one ADP stream item without forwarding raw provider data."""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    elif isinstance(raw, str):
        text = raw
    else:
        return []
    payloads: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        encoded = line[5:].strip()
        if not encoded or encoded == "[DONE]":
            continue
        try:
            payload = json.loads(encoded)
        except (TypeError, ValueError):
            continue
        if isinstance(payload, Mapping):
            payloads.append(dict(payload))
    return payloads


def _event_value(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _event_evidence(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Map only explicit ADP evidence fields into the platform allowlist."""
    raw = _event_value(payload, "evidence", "Evidence", "evidences", "Evidences")
    if not isinstance(raw, list):
        return []
    mapped: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        mapped.append({
            "label": _event_value(item, "label", "Label", "name", "Name"),
            "value": _event_value(item, "value", "Value"),
            "source": _event_value(item, "source", "Source"),
            "capturedAt": _event_value(item, "capturedAt", "CapturedAt"),
            "known": _event_value(item, "known", "Known"),
        })
    return allowlisted_evidence(mapped)


def _safe_trace_id(payload: Mapping[str, Any]) -> str:
    value = _event_value(payload, "traceId", "TraceId", "requestId", "RequestId")
    return value.strip()[:64] if isinstance(value, str) else ""


class ADPAgentProvider:
    """Server-mapped ADP provider with a narrow, safe response boundary."""

    capabilities = frozenset({"shipment.lookup"})

    def __init__(
        self,
        *,
        agent_id: str,
        application_id: str,
        vendor: Any = None,
    ):
        self.agent_id = agent_id.strip()[:128]
        self.application_id = application_id.strip()[:64]
        self.vendor = vendor

    async def execute(self, request: AgentRequest, *, sink: Any = None) -> AgentResponse:
        normalized_query = str(request.query or "").strip()
        if (
            not self.vendor
            or not callable(getattr(self.vendor, "chat", None))
            or request.agent_id != self.agent_id
            or not request.visitor_id.strip()
            or not request.conversation_id.strip()
        ):
            return AgentResponse.upstream_error(normalized_query.upper())

        callback = _ConversationCallback(
            conversation_id=request.conversation_id,
            application_id=self.application_id,
            title=normalized_query,
        )
        contents = [{"Type": "text", "Text": normalized_query}]
        # Private business answers are rendered from recorded tool evidence.
        if request.context_token:
            sink = None
        answer_parts: list[str] = []
        # ADP streams reasoning as text.delta under a separate message whose
        # Type is "thought"; the answer is the "reply" message. We classify each
        # delta by its message id so the answer stays clean and (for a channel
        # that supports it) the thinking is streamed separately.
        message_types: dict[str, str] = {}
        evidence: list[dict[str, Any]] = []
        trace_id = ""
        try:
            stream = self.vendor.chat(
                account_id=request.visitor_id,
                contents=contents,
                conversation_id=request.conversation_id,
                is_new_conversation=False,
                conversation_cb=callback,
                search_network=True,
                custom_variables=({
                    "platform_context_token": request.context_token,
                    "platform_conversation_id": request.conversation_id,
                    "platform_run_id": request.run_id,
                    "platform_agent_id": request.agent_id,
                    "platform_application_id": self.application_id,
                    "platform_tool_request_id": f"adp:{request.run_id}",
                } if request.context_token else {}),
            )
            async for item in stream:
                for payload in _sse_payloads(item):
                    event_type = _event_value(payload, "Type", "type")
                    if not isinstance(event_type, str):
                        continue
                    if event_type.lower() == "error":
                        return AgentResponse.upstream_error(normalized_query.upper())
                    if not trace_id:
                        trace_id = _safe_trace_id(payload)
                    evidence.extend(_event_evidence(payload))
                    lowered = event_type.lower()
                    if lowered in ("message.added", "message.processing", "message.done"):
                        message = _event_value(payload, "Message", "message")
                        if isinstance(message, Mapping):
                            mid = message.get("MessageId") or message.get("message_id")
                            mtype = message.get("Type") or message.get("type")
                            if mid is not None:
                                message_types[str(mid)] = str(mtype or "")
                    elif lowered == "text.delta":
                        delta = _event_value(payload, "Text", "text")
                        if isinstance(delta, str):
                            mid = str(_event_value(payload, "MessageId", "message_id") or "")
                            mtype = message_types.get(mid, "")
                            chunk = delta[:4000]
                            if mtype == "thought":
                                # Reasoning: stream separately when the channel
                                # supports it; never part of the stored answer.
                                if sink is not None and hasattr(sink, "emit_reasoning"):
                                    try:
                                        await sink.emit_reasoning(chunk)
                                    except Exception as exc:
                                        logger.warning(
                                            "streaming sink failed: %s", type(exc).__name__
                                        )
                                        sink = None
                            elif mtype in ("tool_call", "notice"):
                                # Process noise; not shown to the customer.
                                continue
                            else:
                                # "reply" (or an unknown/default) is the answer.
                                answer_parts.append(chunk)
                                if sink is not None:
                                    # A channel send must never abort the run: the
                                    # full answer is still persisted for the portal.
                                    try:
                                        await sink.emit(chunk)
                                    except Exception as exc:
                                        logger.warning(
                                            "streaming sink failed: %s", type(exc).__name__
                                        )
                                        sink = None
        except DeliveryRetryableError:
            raise
        except Exception as exc:
            # Provider messages can contain credentials or upstream payloads;
            # only the exception type is safe for server logs.
            logger.warning("ADP Agent execution failed: %s", type(exc).__name__)
            return AgentResponse.upstream_error(normalized_query.upper())

        if sink is not None:
            try:
                await sink.close()
            except Exception as exc:
                logger.warning("streaming sink close failed: %s", type(exc).__name__)

        summary = "".join(answer_parts).strip()[:2000]
        if not summary:
            return AgentResponse.upstream_error(normalized_query.upper())
        return AgentResponse(
            status="completed",
            query=normalized_query.upper(),
            title="业务查询结果",
            summary=summary,
            evidence=allowlisted_evidence(evidence),
            provider_trace_id=trace_id,
            audit_outcome="completed",
        )
