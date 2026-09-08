"""Cross-instance replay protection for signed channel callbacks."""

from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from core.channel_replay import (
    ChannelReplayError,
    claim_replay_key,
    prune_expired_replay_markers,
)
from core.platform import utc_now
from model.platform import PlatformChannelReplayMarker


CHANNEL = "wechat_official_account"
INSTANCE = "oa-replay"
KEY = "a" * 64


class _NestedTransaction:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


class _FakeDb:
    """Fake session that mimics the unique-constraint behavior of PostgreSQL."""

    def __init__(self, *, existing=None, conflict=False):
        self.existing = existing
        self.conflict = conflict
        self.added = []
        self.deleted = []
        self.expired_ids = []

    async def execute(self, statement):
        compiled = str(statement)
        if compiled.startswith("DELETE"):
            self.deleted.append(compiled)
            return SimpleNamespace()
        if "Id" in compiled and self.expired_ids:
            return SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: list(self.expired_ids))
            )
        return SimpleNamespace(
            scalar_one_or_none=lambda: self.existing,
            scalars=lambda: SimpleNamespace(all=lambda: []),
        )

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        if self.conflict:
            raise IntegrityError("insert", {}, Exception("duplicate key"))

    def begin_nested(self):
        return _NestedTransaction(self)


@pytest.mark.asyncio
async def test_first_signature_is_recorded_with_an_expiry():
    db = _FakeDb()
    await claim_replay_key(
        db,
        channel=CHANNEL,
        channel_instance_id=INSTANCE,
        replay_key=KEY,
        ttl_seconds=300,
    )
    assert len(db.added) == 1
    marker = db.added[0]
    assert isinstance(marker, PlatformChannelReplayMarker)
    assert marker.ReplayKey == KEY
    assert marker.ExpiresAt > utc_now()


@pytest.mark.asyncio
async def test_a_replayed_signature_is_rejected():
    existing = PlatformChannelReplayMarker(
        Id=uuid.uuid4(),
        Channel=CHANNEL,
        ChannelInstanceId=INSTANCE,
        ReplayKey=KEY,
        ExpiresAt=utc_now() + timedelta(seconds=300),
    )
    db = _FakeDb(existing=existing)
    with pytest.raises(ChannelReplayError, match="重复提交"):
        await claim_replay_key(
            db,
            channel=CHANNEL,
            channel_instance_id=INSTANCE,
            replay_key=KEY,
            ttl_seconds=300,
        )
    assert db.added == []


@pytest.mark.asyncio
async def test_a_concurrent_instance_losing_the_race_is_rejected():
    """The unique constraint is the real guard, not the preceding read."""
    db = _FakeDb(conflict=True)
    with pytest.raises(ChannelReplayError, match="重复提交"):
        await claim_replay_key(
            db,
            channel=CHANNEL,
            channel_instance_id=INSTANCE,
            replay_key=KEY,
            ttl_seconds=300,
        )


@pytest.mark.asyncio
async def test_invalid_window_and_key_fail_closed():
    db = _FakeDb()
    with pytest.raises(ChannelReplayError):
        await claim_replay_key(
            db,
            channel=CHANNEL,
            channel_instance_id=INSTANCE,
            replay_key="",
            ttl_seconds=300,
        )
    with pytest.raises(ChannelReplayError):
        await claim_replay_key(
            db,
            channel=CHANNEL,
            channel_instance_id=INSTANCE,
            replay_key=KEY,
            ttl_seconds=0,
        )
    with pytest.raises(ChannelReplayError):
        await claim_replay_key(
            db,
            channel=CHANNEL,
            channel_instance_id=INSTANCE,
            replay_key=KEY,
            ttl_seconds=48 * 60 * 60,
        )
    assert db.added == []


@pytest.mark.asyncio
async def test_pruning_is_bounded_and_reports_nothing_to_do():
    empty = _FakeDb()
    assert await prune_expired_replay_markers(empty) == 0
    assert empty.deleted == []

    stale = _FakeDb()
    stale.expired_ids = [uuid.uuid4(), uuid.uuid4()]
    assert await prune_expired_replay_markers(stale, limit=2) == 2
    assert len(stale.deleted) == 1
