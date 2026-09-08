"""Deliver agent text to a chat channel while it is still being produced.

The upstream ADP call is a real SSE stream of ``text.delta`` events, so a
customer can watch the answer being written instead of waiting for the whole
response. A channel with no incremental message API (WeChat Official Account)
approximates that by sending several messages in sequence, cut at sentence
boundaries so each bubble reads as a complete thought.

Two properties matter more than smoothness:

- **No duplicates.** Every chunk carries its own idempotency key and the sink
  records how many chunks were sent, so a retry resumes instead of replaying
  bubbles the customer already read.
- **Never break the run.** A failed send degrades to "stop streaming"; the full
  answer is still persisted and available in the portal.
"""

from __future__ import annotations

import logging
from typing import Any

from integrations.channels.text_format import split_at_boundary, to_plain_text


logger = logging.getLogger(__name__)

# Below this, a bubble feels like a fragment; above the max, one bubble grows
# past what the channel renders comfortably.
DEFAULT_MIN_CHUNK_CHARS = 60
DEFAULT_MAX_CHUNK_CHARS = 600
# Providers are chatty; this caps how many bubbles one answer may produce.
DEFAULT_MAX_CHUNKS = 12


class ChannelStreamSink:
    """Buffer agent deltas and push readable chunks to one channel sender."""

    def __init__(
        self,
        sender: Any,
        *,
        open_id_payload: dict[str, Any],
        idempotency_prefix: str,
        min_chars: int = DEFAULT_MIN_CHUNK_CHARS,
        max_chars: int = DEFAULT_MAX_CHUNK_CHARS,
        max_chunks: int = DEFAULT_MAX_CHUNKS,
        start_sequence: int = 0,
    ):
        self._sender = sender
        self._payload = dict(open_id_payload)
        self._prefix = idempotency_prefix
        self._min_chars = min_chars
        self._max_chars = max_chars
        self._max_chunks = max_chunks
        self._buffer = ""
        self._sequence = start_sequence
        self.sent_chunks = 0
        self.sent_characters = 0
        self.failed = False

    @property
    def sequence(self) -> int:
        """Number of chunks this sink has attempted, for resume bookkeeping."""
        return self._sequence

    async def emit(self, text: str) -> None:
        if self.failed or not isinstance(text, str) or not text:
            return
        self._buffer += text
        while True:
            if self._sequence >= self._max_chunks:
                # Stop streaming rather than flooding the channel. The complete
                # answer still reaches the portal.
                self.failed = True
                logger.info("streaming stopped after %s chunks", self._sequence)
                return
            chunk, rest = split_at_boundary(
                self._buffer, min_chars=self._min_chars, max_chars=self._max_chars
            )
            if not chunk:
                return
            self._buffer = rest
            await self._send(chunk)
            if self.failed:
                return

    async def close(self) -> None:
        """Send whatever is left once the upstream stream ends."""
        if self.failed:
            return
        remaining = self._buffer
        self._buffer = ""
        if remaining.strip() and self._sequence < self._max_chunks:
            await self._send(remaining)

    async def _send(self, chunk: str) -> None:
        content = to_plain_text(chunk)
        if not content:
            return
        self._sequence += 1
        payload = dict(self._payload)
        payload["summary"] = content
        # A per-chunk key lets an upstream provider deduplicate a resend and
        # keeps a resumed task from replaying earlier bubbles.
        payload["deliveryIdempotencyKey"] = f"{self._prefix}:{self._sequence}"
        try:
            receipt = await self._sender.send(payload=payload)
        except Exception as exc:
            # Includes retryable and uncertain transport errors. Streaming is a
            # presentation nicety; the run must still finish and persist.
            self.failed = True
            logger.warning("streaming chunk %s failed: %s", self._sequence, type(exc).__name__)
            return
        status = getattr(receipt, "status", None)
        if status is not None and status != "delivered":
            self.failed = True
            logger.warning("streaming chunk %s not delivered: %s", self._sequence, status)
            return
        self.sent_chunks += 1
        self.sent_characters += len(content)
