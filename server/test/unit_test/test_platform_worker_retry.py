from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from core.delivery import DeliveryRetryableError, DeliveryUncertainError
from core.platform_worker import process_platform_reply_task
from model.platform import PlatformDeliveryTask


@pytest.mark.asyncio
async def test_reply_sender_receives_stable_idempotency_key():
    inbound_id = str(uuid.uuid4())
    payload = {
        "inboundMessageId": inbound_id,
        "channel": "wechat-service-account",
        "deliveryIdempotencyKey": f"platform-reply:{inbound_id}",
    }
    task = PlatformDeliveryTask(Payload=payload)
    sender = AsyncMock()
    sender.send.return_value = {"providerMessageId": "provider-42"}

    outcome = await process_platform_reply_task(lambda: None, task, sender=sender)

    assert outcome.result["status"] == "delivered"
    sent_payload = sender.send.await_args.kwargs["payload"]
    assert sent_payload["deliveryIdempotencyKey"] == f"platform-reply:{inbound_id}"
    assert outcome.result["providerResult"] == {"providerMessageId": "provider-42"}


@pytest.mark.asyncio
async def test_reply_sender_preserves_explicit_retryable_failure():
    inbound_id = str(uuid.uuid4())
    task = PlatformDeliveryTask(
        Payload={
            "inboundMessageId": inbound_id,
            "channel": "wechat-service-account",
        }
    )
    sender = AsyncMock()
    sender.send.side_effect = DeliveryRetryableError("provider_timeout")

    with pytest.raises(DeliveryRetryableError, match="provider_timeout"):
        await process_platform_reply_task(lambda: None, task, sender=sender)


@pytest.mark.asyncio
async def test_reply_sender_unknown_failure_is_uncertain_and_not_retryable():
    inbound_id = str(uuid.uuid4())
    task = PlatformDeliveryTask(
        Payload={
            "inboundMessageId": inbound_id,
            "channel": "wechat-service-account",
        }
    )
    sender = AsyncMock()
    sender.send.side_effect = RuntimeError("connection dropped after send")

    with pytest.raises(DeliveryUncertainError, match="channel_send_result_unknown"):
        await process_platform_reply_task(lambda: None, task, sender=sender)
