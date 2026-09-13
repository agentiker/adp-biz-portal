from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest

from core.delivery import DeliveryRejectedError, DeliveryRetryableError, DeliveryUncertainError
from core.platform import utc_now
from core.platform_worker import process_platform_reply_task
from model.account import Account, AccountStatus
from model.platform import (
    EnterpriseStatus,
    PlatformDeliveryTask,
    PlatformEnterprise,
    PlatformInboundMessage,
    PlatformMembership,
    PlatformRole,
    PlatformStatus,
    PlatformUser,
)


CHANNEL = "wechat_official_account"


class _FakeSender:
    """Minimal channel sender: records what it was asked to deliver."""

    def __init__(self, *, result=None, error=None, channel: str | None = None):
        self.result = result if result is not None else {}
        self.error = error
        self.calls = []
        if channel is not None:
            self.channel = channel

    async def send(self, *, payload=None, message=None):
        self.calls.append(payload)
        if self.error is not None:
            raise self.error
        return self.result


class _AuthorizedDb:
    """Fake session returning a fully authorized, still-valid reply scope."""

    def __init__(self, *, inbound_status: str = "processed", reply_window_expires_at=None, membership=True):
        self.account = Account(Id=uuid.uuid4(), Status=AccountStatus.ACTIVE)
        self.user = PlatformUser(
            Id=uuid.uuid4(),
            AccountId=self.account.Id,
            Status=PlatformStatus.ACTIVE,
            Role=PlatformRole.CUSTOMER,
        )
        self.enterprise = PlatformEnterprise(
            Id=uuid.uuid4(),
            Name="Reply Enterprise",
            CustomerCode="REPLY-001",
            Status=EnterpriseStatus.ACTIVE,
        )
        self.inbound = PlatformInboundMessage(
            Id=uuid.uuid4(),
            ChannelInstanceId="oa-reply",
            ExternalMessageId="external-1",
            ExternalConversationId="oa-reply:openid",
            SenderIdentityId="openid",
            TraceId="trace",
            Status=inbound_status,
            ReplyWindowExpiresAt=reply_window_expires_at,
        )
        self.membership = (
            PlatformMembership(
                Id=uuid.uuid4(),
                UserId=self.user.Id,
                EnterpriseId=self.enterprise.Id,
                MembershipRole=PlatformRole.CUSTOMER,
                Active=True,
            )
            if membership
            else None
        )
        self.audits = []
        self.committed = False

    def payload(self, **overrides):
        inbound_id = str(self.inbound.Id)
        payload = {
            "inboundMessageId": inbound_id,
            "accountId": str(self.account.Id),
            "platformUserId": str(self.user.Id),
            "platformSessionId": None,
            "enterpriseId": str(self.enterprise.Id),
            "channel": CHANNEL,
            "channelInstanceId": self.inbound.ChannelInstanceId,
            "deliveryIdempotencyKey": f"platform-reply:{inbound_id}",
        }
        payload.update(overrides)
        return payload

    # --- AsyncSession surface used by the handler -------------------------
    async def get(self, model, primary_key):
        if primary_key is None:
            return None
        for candidate in (self.inbound, self.user, self.account, self.enterprise):
            if isinstance(candidate, model) and str(candidate.Id) == str(primary_key):
                return candidate
        return None

    async def execute(self, _statement):
        return SimpleNamespace(scalar_one_or_none=lambda: self.membership)

    def add(self, value):
        self.audits.append(value)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        return None

    async def close(self):
        return None


def _sessionmaker(db):
    return lambda: db


@pytest.mark.asyncio
async def test_reply_sender_receives_stable_idempotency_key():
    db = _AuthorizedDb()
    task = PlatformDeliveryTask(Payload=db.payload())
    sender = _FakeSender(result={"providerMessageId": "provider-42"})

    outcome = await process_platform_reply_task(_sessionmaker(db), task, sender=sender)

    assert outcome.result["status"] == "delivered"
    sent_payload = sender.calls[0]
    assert sent_payload["deliveryIdempotencyKey"] == f"platform-reply:{db.inbound.Id}"
    assert outcome.result["providerResult"] == {"providerMessageId": "provider-42"}


@pytest.mark.asyncio
async def test_reply_sender_preserves_explicit_retryable_failure():
    db = _AuthorizedDb()
    task = PlatformDeliveryTask(Payload=db.payload())
    sender = _FakeSender(error=DeliveryRetryableError("provider_timeout"))

    with pytest.raises(DeliveryRetryableError, match="provider_timeout"):
        await process_platform_reply_task(_sessionmaker(db), task, sender=sender)


@pytest.mark.asyncio
async def test_reply_sender_unknown_failure_is_uncertain_and_not_retryable():
    db = _AuthorizedDb()
    task = PlatformDeliveryTask(Payload=db.payload())
    sender = _FakeSender(error=RuntimeError("connection dropped after send"))

    with pytest.raises(DeliveryUncertainError, match="channel_send_result_unknown"):
        await process_platform_reply_task(_sessionmaker(db), task, sender=sender)


@pytest.mark.asyncio
async def test_reply_requires_identity_fields_in_every_payload():
    """Authorization is not optional: a payload without identity is rejected."""
    db = _AuthorizedDb()
    task = PlatformDeliveryTask(
        Payload={"inboundMessageId": str(db.inbound.Id), "channel": CHANNEL},
    )
    sender = _FakeSender()

    with pytest.raises(DeliveryRejectedError, match="invalid_task_payload"):
        await process_platform_reply_task(_sessionmaker(db), task, sender=sender)
    assert sender.calls == []


@pytest.mark.asyncio
async def test_reply_is_rejected_after_membership_is_removed():
    db = _AuthorizedDb(membership=False)
    task = PlatformDeliveryTask(Payload=db.payload())
    sender = _FakeSender()

    with pytest.raises(DeliveryRejectedError, match="authorization_revoked"):
        await process_platform_reply_task(_sessionmaker(db), task, sender=sender)
    assert sender.calls == []


@pytest.mark.asyncio
async def test_reply_is_rejected_once_the_channel_window_closed():
    db = _AuthorizedDb(reply_window_expires_at=utc_now() - timedelta(seconds=1))
    task = PlatformDeliveryTask(Payload=db.payload())
    sender = _FakeSender()

    with pytest.raises(DeliveryRejectedError, match="reply_window_expired"):
        await process_platform_reply_task(_sessionmaker(db), task, sender=sender)
    # Sending outside the protocol window would be reported as success while
    # the provider silently refuses it.
    assert sender.calls == []


@pytest.mark.asyncio
async def test_sender_is_selected_per_channel_instance():
    db = _AuthorizedDb()
    task = PlatformDeliveryTask(Payload=db.payload())
    wechat = _FakeSender(result={"providerMessageId": "wechat-1"})
    wecom = _FakeSender()

    outcome = await process_platform_reply_task(
        _sessionmaker(db),
        task,
        sender={CHANNEL: wechat, "wecom_bot": wecom},
    )

    assert outcome.result["providerResult"] == {"providerMessageId": "wechat-1"}
    assert wecom.calls == []


@pytest.mark.asyncio
async def test_reply_is_rejected_when_no_sender_owns_the_channel():
    db = _AuthorizedDb()
    task = PlatformDeliveryTask(Payload=db.payload())
    other = _FakeSender()

    with pytest.raises(DeliveryRejectedError, match="channel_sender_not_configured"):
        await process_platform_reply_task(
            _sessionmaker(db),
            task,
            sender={"wecom_bot": other},
        )
    assert other.calls == []


@pytest.mark.asyncio
async def test_a_sender_declaring_another_channel_is_never_used():
    """A 企微 sender must not be handed a WeChat reply."""
    db = _AuthorizedDb()
    task = PlatformDeliveryTask(Payload=db.payload())
    wrong = _FakeSender(channel="wecom_bot")

    with pytest.raises(DeliveryRejectedError, match="channel_sender_not_configured"):
        await process_platform_reply_task(_sessionmaker(db), task, sender=wrong)
    assert wrong.calls == []
