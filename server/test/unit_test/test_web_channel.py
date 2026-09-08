from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.platform import PlatformContext
from integrations.channels.web import WebChannelAdapter
from model.platform import PlatformEnterprise, PlatformUser


def _context() -> PlatformContext:
    account = SimpleNamespace(Id=uuid.uuid4())
    user = PlatformUser(Id=uuid.uuid4(), AccountId=account.Id, Name="Web User")
    session = SimpleNamespace(Id=uuid.uuid4())
    return PlatformContext(
        user=user,
        account=account,
        session=session,
        permissions=frozenset({"shipment.read"}),
    )


def test_web_adapter_uses_authenticated_identity_and_stable_message_id():
    context = _context()
    conversation_id = str(uuid.uuid4())
    envelope = WebChannelAdapter().normalize(
        context=context,
        text=" BL-001 ",
        trace_id="trace-web-1",
        message_id="provider-message-1",
        conversation_id=conversation_id,
    )

    assert envelope.message.channel_instance_id == "web-portal"
    assert envelope.message.external_message_id == "provider-message-1"
    assert envelope.message.external_conversation_id == conversation_id
    assert envelope.message.sender_identity_id == str(context.user.Id)
    assert envelope.message.text == "BL-001"
    assert envelope.task_payload["platformUserId"] == str(context.user.Id)
    assert envelope.task_payload["platformSessionId"] == str(context.session.Id)
    assert envelope.task_payload["conversationId"] == conversation_id
    assert envelope.conversation_id == conversation_id


def test_web_adapter_does_not_accept_client_scope_fields():
    context = _context()
    envelope = WebChannelAdapter().normalize(
        context=context,
        text="BL-002",
        trace_id="trace-web-2",
        message_id="provider-message-2",
    )

    assert envelope.task_payload["enterpriseId"] is None
    assert envelope.task_payload["platformUserId"] == str(context.user.Id)
    assert envelope.task_payload["platformSessionId"] == str(context.session.Id)
    assert envelope.message.payload["accountId"] == str(context.account.Id)


def test_web_adapter_rejects_invalid_message_and_conversation():
    context = _context()
    with pytest.raises(Exception, match="消息文本"):
        WebChannelAdapter().normalize(context=context, text=" ", trace_id="trace")
    with pytest.raises(Exception, match="会话 ID"):
        WebChannelAdapter().normalize(
            context=context,
            text="BL-003",
            trace_id="trace",
            conversation_id="not-a-uuid",
        )


@pytest.mark.asyncio
async def test_web_channel_route_persists_normalized_callback_and_ignores_client_identity(monkeypatch):
    from test.app_bootstrap import ensure_app

    ensure_app()
    import router.platform as platform_router

    context = _context()
    enterprise = PlatformEnterprise(Id=uuid.uuid4(), Name="Web Enterprise", CustomerCode="WEB-001")
    captured: dict[str, object] = {}

    async def fake_load(_db, token):
        assert token == "web-token"
        return context

    async def fake_scope(_db, user, *, enterprise_id=None):
        assert user is context.user
        assert enterprise_id == str(enterprise.Id)
        return enterprise

    async def fake_record(_db, *, message, task_type, task_payload, **_kwargs):
        captured["message"] = message
        captured["taskType"] = task_type
        captured["taskPayload"] = task_payload
        inbound = SimpleNamespace(Id=uuid.uuid4(), Status="queued")
        task = SimpleNamespace(Id=uuid.uuid4())
        return inbound, task, True

    monkeypatch.setattr(platform_router, "load_platform_context", fake_load)
    monkeypatch.setattr(platform_router, "resolve_enterprise_scope", fake_scope)
    monkeypatch.setattr(platform_router, "record_inbound_message", fake_record)

    db = SimpleNamespace(commit=AsyncMock())
    request = SimpleNamespace(
        ctx=SimpleNamespace(db=db),
        headers={"Authorization": "Bearer web-token", "X-Request-Id": "trace-web-route"},
        cookies={},
        json={
            "text": "BL-004",
            "messageId": "web-message-4",
            # Identity fields from the browser are ignored; only the enterprise
            # scope is accepted, and only after a membership check.
            "platformUserId": str(uuid.uuid4()),
            "platformSessionId": str(uuid.uuid4()),
            "enterpriseId": str(enterprise.Id),
        },
    )

    response = await platform_router.WebChannelInboundApi().post(request)
    payload = json.loads(response.body.decode("utf-8"))
    task_payload = captured["taskPayload"]
    message = captured["message"]

    assert response.status == 201
    assert payload["created"] is True
    assert payload["channel"] == "web"
    assert task_payload["platformUserId"] == str(context.user.Id)
    assert task_payload["platformSessionId"] == str(context.session.Id)
    assert task_payload["enterpriseId"] == str(enterprise.Id)
    assert message.sender_identity_id == str(context.user.Id)
    assert message.external_message_id == "web-message-4"
    db.commit.assert_awaited_once()

    artifact = Path(__file__).resolve().parents[3] / "output" / "tests" / "m2-worker-02-web-channel.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        json.dumps(
            {
                "channel": payload["channel"],
                "taskType": captured["taskType"],
                "serverUserId": task_payload["platformUserId"],
                "serverEnterpriseId": task_payload["enterpriseId"],
                "clientIdentityIgnored": True,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    assert json.loads(artifact.read_text(encoding="utf-8"))["clientIdentityIgnored"] is True


class _EnterpriseScopeDb:
    """Fake session returning a fixed set of active enterprises for a user."""

    def __init__(self, enterprises):
        self.enterprises = enterprises

    async def execute(self, _statement):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: list(self.enterprises)))


@pytest.mark.asyncio
async def test_single_enterprise_is_selected_without_an_explicit_scope():
    from core.platform import resolve_enterprise_scope

    only = PlatformEnterprise(Id=uuid.uuid4(), Name="Only", CustomerCode="ONE")
    resolved = await resolve_enterprise_scope(_EnterpriseScopeDb([only]), _context().user)
    assert resolved is only


@pytest.mark.asyncio
async def test_multi_enterprise_user_must_state_the_scope():
    """Silently choosing one of several tenants would answer with wrong data."""
    from core.error.platform import PlatformForbidden
    from core.platform import resolve_enterprise_scope

    first = PlatformEnterprise(Id=uuid.uuid4(), Name="Alpha", CustomerCode="A")
    second = PlatformEnterprise(Id=uuid.uuid4(), Name="Beta", CustomerCode="B")
    db = _EnterpriseScopeDb([first, second])

    with pytest.raises(PlatformForbidden, match="明确企业范围"):
        await resolve_enterprise_scope(db, _context().user)

    chosen = await resolve_enterprise_scope(
        _EnterpriseScopeDb([first, second]),
        _context().user,
        enterprise_id=str(second.Id),
    )
    assert chosen is second


@pytest.mark.asyncio
async def test_requested_scope_must_match_an_active_membership():
    from core.error.platform import PlatformForbidden
    from core.platform import resolve_enterprise_scope

    mine = PlatformEnterprise(Id=uuid.uuid4(), Name="Mine", CustomerCode="M")
    db = _EnterpriseScopeDb([mine])

    with pytest.raises(PlatformForbidden, match="没有可访问的企业范围"):
        await resolve_enterprise_scope(db, _context().user, enterprise_id=str(uuid.uuid4()))
