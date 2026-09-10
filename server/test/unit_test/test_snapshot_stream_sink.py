"""SnapshotStreamSink: cumulative snapshots, throttle, final frame, cap, fail-safe."""

from __future__ import annotations

import pytest

from integrations.channels.stream_sink import SnapshotStreamSink


class _Recorder:
    def __init__(self, *, fail=False):
        self.frames = []
        self._fail = fail

    async def push(self, content, *, is_final):
        if self._fail:
            raise RuntimeError("ws down")
        self.frames.append((content, is_final))


@pytest.mark.asyncio
async def test_frames_are_cumulative_and_final_is_flagged():
    rec = _Recorder()
    sink = SnapshotStreamSink(rec.push, min_interval=0.0)  # push every delta
    await sink.emit("你好")
    await sink.emit("，世界")
    await sink.close()
    assert rec.frames == [("你好", False), ("你好，世界", False), ("你好，世界", True)]


@pytest.mark.asyncio
async def test_identical_nonfinal_snapshot_is_not_repushed_but_final_is():
    rec = _Recorder()
    sink = SnapshotStreamSink(rec.push, min_interval=0.0)
    await sink.emit("hi")
    await sink.emit("")  # empty delta → no change, no push
    await sink.close()   # final always pushed even though content unchanged
    assert rec.frames == [("hi", False), ("hi", True)]


@pytest.mark.asyncio
async def test_snapshot_is_capped():
    rec = _Recorder()
    sink = SnapshotStreamSink(rec.push, min_interval=0.0, max_chars=100)
    await sink.emit("x" * 500)
    await sink.close()
    assert all(len(content) <= 100 for content, _ in rec.frames)


@pytest.mark.asyncio
async def test_markdown_is_flattened():
    rec = _Recorder()
    sink = SnapshotStreamSink(rec.push, min_interval=0.0)
    await sink.emit("**bold** `code`")
    await sink.close()
    final = rec.frames[-1][0]
    assert "**" not in final and "`" not in final and "bold" in final


@pytest.mark.asyncio
async def test_push_failure_stops_streaming_without_raising():
    rec = _Recorder(fail=True)
    sink = SnapshotStreamSink(rec.push, min_interval=0.0)
    await sink.emit("hi")   # push raises internally, swallowed
    await sink.emit("more")  # sink is now disabled, no further attempts
    await sink.close()
    assert rec.frames == []  # nothing recorded; the run is never broken


def _think_render(answer: str, reasoning: str) -> str:
    r, a = reasoning.strip(), answer
    if r and a:
        return f"<think>{r}</think>\n{a}"
    if r:
        return f"<think>{r}</think>"
    return a


@pytest.mark.asyncio
async def test_render_separates_reasoning_from_answer():
    rec = _Recorder()
    sink = SnapshotStreamSink(rec.push, min_interval=0.0, render=_think_render)
    await sink.emit_reasoning("先分析")      # reasoning arrives first
    await sink.emit_reasoning("提单状态")
    await sink.emit("已到港。")               # then the answer
    await sink.close()
    # Reasoning folds into <think>; the answer appends below and stays clean.
    assert rec.frames[0] == ("<think>先分析</think>", False)
    assert rec.frames[-1] == ("<think>先分析提单状态</think>\n已到港。", True)
    # Every frame keeps reasoning folded.
    assert all(c.startswith("<think>") for c, _ in rec.frames)


@pytest.mark.asyncio
async def test_render_answer_only_when_no_reasoning():
    rec = _Recorder()
    sink = SnapshotStreamSink(rec.push, min_interval=0.0, render=_think_render)
    await sink.emit("直接回答")
    await sink.close()
    assert rec.frames[-1] == ("直接回答", True)
    assert "<think>" not in rec.frames[-1][0]

