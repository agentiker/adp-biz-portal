"""Streaming chunk delivery: readability, no duplicates, never break the run."""

from __future__ import annotations

import pytest

from integrations.channels.base import DeliveryReceipt
from integrations.channels.stream_sink import ChannelStreamSink


PAYLOAD = {"externalConversationId": "oa-1:openid_a", "channel": "wechat_official_account"}


class _RecordingSender:
    def __init__(self, *, results=None, error=None):
        self.calls = []
        self._results = list(results or [])
        self._error = error

    async def send(self, *, payload=None, message=None):
        self.calls.append(payload)
        if self._error is not None:
            raise self._error
        if self._results:
            return self._results.pop(0)
        return DeliveryReceipt(status="delivered")


def _sink(sender, **kwargs):
    options = {"open_id_payload": PAYLOAD, "idempotency_prefix": "platform-reply:abc"}
    options.update(kwargs)
    return ChannelStreamSink(sender, **options)


@pytest.mark.asyncio
async def test_short_deltas_are_buffered_until_a_sentence_ends():
    sender = _RecordingSender()
    sink = _sink(sender, min_chars=10)

    await sink.emit("正在核对")
    assert sender.calls == []  # no boundary yet

    await sink.emit("提单信息，请稍候。")
    assert len(sender.calls) == 1
    assert sender.calls[0]["summary"] == "正在核对提单信息，请稍候。"


@pytest.mark.asyncio
async def test_each_chunk_carries_its_own_idempotency_key():
    sender = _RecordingSender()
    sink = _sink(sender, min_chars=5)

    # Separate flushes, because each emit already ends on a boundary and clears
    # the buffer.
    await sink.emit("第一句足够长了。")
    await sink.emit("第二句也足够长。")

    keys = [call["deliveryIdempotencyKey"] for call in sender.calls]
    assert keys == ["platform-reply:abc:1", "platform-reply:abc:2"]


@pytest.mark.asyncio
async def test_a_flush_takes_everything_up_to_the_last_complete_sentence():
    """Fewer, fuller bubbles: each send is an API call under a rate limit."""
    sender = _RecordingSender()
    sink = _sink(sender, min_chars=5)

    await sink.emit("第一句。")
    await sink.emit("第二句。尾巴")

    assert len(sender.calls) == 1
    assert sender.calls[0]["summary"] == "第一句。第二句。"
    # The unfinished tail waits for more text.
    await sink.close()
    assert sender.calls[1]["summary"] == "尾巴"


@pytest.mark.asyncio
async def test_resume_continues_the_sequence_instead_of_replaying():
    """A retry must not re-send bubbles the customer already read."""
    sender = _RecordingSender()
    sink = _sink(sender, min_chars=5, start_sequence=3)

    await sink.emit("续发一句。")

    assert sender.calls[0]["deliveryIdempotencyKey"] == "platform-reply:abc:4"


@pytest.mark.asyncio
async def test_markdown_is_normalized_per_chunk():
    sender = _RecordingSender()
    sink = _sink(sender, min_chars=5)

    await sink.emit("**已到港**，详见 [官网](https://x/y)。")

    assert sender.calls[0]["summary"] == "已到港，详见 官网 https://x/y。"


@pytest.mark.asyncio
async def test_close_flushes_the_tail_without_a_boundary():
    sender = _RecordingSender()
    sink = _sink(sender, min_chars=10)

    await sink.emit("结尾没有标点")
    assert sender.calls == []

    await sink.close()
    assert len(sender.calls) == 1
    assert sender.calls[0]["summary"] == "结尾没有标点"


@pytest.mark.asyncio
async def test_close_sends_nothing_when_the_buffer_is_empty():
    sender = _RecordingSender()
    sink = _sink(sender, min_chars=5)
    await sink.emit("整句。")
    await sink.close()
    assert len(sender.calls) == 1


@pytest.mark.asyncio
async def test_a_failed_send_stops_streaming_but_does_not_raise():
    """The run must finish and persist even when the channel send fails."""
    sender = _RecordingSender(error=RuntimeError("transport down"))
    sink = _sink(sender, min_chars=5)

    await sink.emit("第一句。")
    await sink.emit("第二句。")
    await sink.close()

    assert sink.failed is True
    assert sink.sent_chunks == 0
    # Only one attempt: streaming stops instead of hammering the channel.
    assert len(sender.calls) == 1


@pytest.mark.asyncio
async def test_an_undelivered_receipt_also_stops_streaming():
    sender = _RecordingSender(
        results=[DeliveryReceipt(status="uncertain", uncertain=True)]
    )
    sink = _sink(sender, min_chars=5)

    await sink.emit("第一句。")
    await sink.emit("第二句。")

    assert sink.failed is True
    assert sink.sent_chunks == 0
    assert len(sender.calls) == 1


@pytest.mark.asyncio
async def test_chunk_count_is_capped():
    sender = _RecordingSender()
    sink = _sink(sender, min_chars=1, max_chunks=3)

    for _ in range(10):
        await sink.emit("句。")

    assert len(sender.calls) == 3
    assert sink.failed is True


@pytest.mark.asyncio
async def test_a_run_on_paragraph_is_cut_at_the_maximum():
    sender = _RecordingSender()
    sink = _sink(sender, min_chars=5, max_chars=20)

    await sink.emit("无标点" * 20)

    assert sender.calls
    assert all(len(call["summary"]) <= 20 for call in sender.calls)


@pytest.mark.asyncio
async def test_counters_track_what_actually_reached_the_customer():
    sender = _RecordingSender()
    sink = _sink(sender, min_chars=5)

    await sink.emit("第一句。第二句。")
    await sink.close()

    assert sink.sent_chunks == len(sender.calls)
    assert sink.sent_characters == sum(len(call["summary"]) for call in sender.calls)


@pytest.mark.asyncio
async def test_a_provider_without_the_sink_parameter_still_runs():
    """The sink is an optional extension, not a breaking protocol change."""
    from integrations.adp.provider import AgentRequest, AgentResponse
    from core.platform_worker import _execute_provider, _provider_accepts_sink

    class _LegacyProvider:
        capabilities = frozenset({"shipment.lookup"})

        async def execute(self, request):
            return AgentResponse.upstream_error("BL-1")

    class _StreamingProvider:
        capabilities = frozenset({"shipment.lookup"})

        def __init__(self):
            self.received_sink = "unset"

        async def execute(self, request, *, sink=None):
            self.received_sink = sink
            return AgentResponse.upstream_error("BL-1")

    request = AgentRequest(
        agent_id="a",
        conversation_id="c",
        run_id="r",
        channel="wechat_official_account",
        query="BL-1",
        customer_code="C",
        trace_id="t",
        visitor_id="v",
    )
    legacy = _LegacyProvider()
    assert _provider_accepts_sink(legacy) is False
    # Must not raise a TypeError for every message.
    assert await _execute_provider(legacy, request, sink=object()) is not None

    streaming = _StreamingProvider()
    assert _provider_accepts_sink(streaming) is True
    sentinel = object()
    await _execute_provider(streaming, request, sink=sentinel)
    assert streaming.received_sink is sentinel
