"""Shared channel inbound orchestration: identity → task payload → enqueue.

Every channel that produces a normalized inbound message resolves it to a bound
platform user, stamps the durable task payload with that identity, and enqueues
it — identically for the WeChat 公众号 callback, the 微信客服 pull loop and any
future channel. This is the one place that logic lives, so a new channel never
re-implements (and drifts from) the identity/authz boundary. Enterprise scope
is deliberately NOT resolved here — the worker selects it from the platform
user's active memberships at execution time.

Callers own the transaction: this function reads/writes but never commits, and
never touches the channel's wire protocol (verify/decrypt/reply stay in the
adapter and the caller).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from core.channel_identity import external_identity_fingerprint, resolve_active_channel_identity
from channels.contracts import InboundMessageInput
from core.delivery import record_inbound_message
from core.platform import create_audit
from model.platform import PlatformChannelIdentity, PlatformInboundMessage


@dataclass(frozen=True)
class InboundIngressResult:
    """Outcome of resolving + enqueuing one inbound message.

    ``identity`` is None when the sender is not bound to any active platform
    user (a reject audit is written); the caller decides how to answer an
    unbound sender (a passive guidance reply, a skip, etc.). ``created`` is
    False for a duplicate external message id.
    """

    identity: PlatformChannelIdentity | None
    inbound: PlatformInboundMessage | None
    created: bool

    @property
    def bound(self) -> bool:
        return self.identity is not None


async def resolve_and_enqueue_inbound(
    db: AsyncSession,
    *,
    channel: str,
    channel_instance_id: str,
    external_identity_id: str,
    message: InboundMessageInput,
    base_task_payload: Mapping[str, Any],
    trace_id: str,
    task_type: str,
    max_attempts: int,
) -> InboundIngressResult:
    """Resolve the sender's binding, stamp the task payload, and enqueue.

    Returns without enqueuing (identity=None) when the sender is unbound, after
    recording a redacted reject audit. Does not commit.
    """
    identity = await resolve_active_channel_identity(
        db,
        channel=channel,
        channel_instance_id=channel_instance_id,
        external_identity_id=external_identity_id,
    )
    if identity is None:
        await create_audit(
            db,
            actor_account_id=None,
            action="channel.inbound.reject",
            target_type="platform_channel_identity",
            target_id=None,
            trace_id=trace_id,
            outcome="rejected",
            metadata={
                "channel": channel,
                "channelInstanceId": channel_instance_id,
                "externalIdentityFingerprint": external_identity_fingerprint(external_identity_id),
                "reason": "channel_identity_not_bound",
            },
        )
        return InboundIngressResult(identity=None, inbound=None, created=False)

    task_payload = dict(base_task_payload)
    task_payload.update(
        {
            "platformUserId": str(identity.UserId),
            # Enterprise scope is selected by the worker from the platform user's
            # active memberships. Channel identity is platform-level.
            "enterpriseId": None,
            "accountId": str(identity.AccountId),
            "channel": channel,
            "traceId": trace_id,
        }
    )
    inbound, _task, created = await record_inbound_message(
        db,
        message=message,
        task_type=task_type,
        task_payload=task_payload,
        max_attempts=max_attempts,
    )
    return InboundIngressResult(identity=identity, inbound=inbound, created=created)
