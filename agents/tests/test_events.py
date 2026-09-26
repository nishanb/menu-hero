"""Event model, parsing and emitters."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from agents.core.events import (
    AgentCompleted,
    AgentFailed,
    AgentStarted,
    CollectingEventEmitter,
    EventEmitter,
    NullEventEmitter,
    QueueEventEmitter,
    TokenStream,
    ToolCompleted,
    ToolStarted,
    parse_event,
)
from agents.schemas.agent import AgentResult


def test_event_types_and_json_roundtrip() -> None:
    result = AgentResult(response="r", agent="example")
    events = [
        AgentStarted(run_id="1", agent="example", message="m"),
        ToolStarted(run_id="1", agent="example", tool="word_count", input={"text": "m"}),
        ToolCompleted(
            run_id="1", agent="example", tool="word_count", output={"words": 1}, duration_ms=0.5
        ),
        TokenStream(run_id="1", agent="example", token="t"),
        AgentCompleted(run_id="1", agent="example", result=result),
        AgentFailed(run_id="1", agent="example", error="e", error_type="RuntimeError"),
    ]
    assert [event.type for event in events] == [
        "agent_started",
        "tool_started",
        "tool_completed",
        "token",
        "agent_completed",
        "agent_failed",
    ]
    for event in events:
        parsed = parse_event(event.model_dump_json())
        assert type(parsed) is type(event)
        assert parsed == event
        assert parse_event(event.model_dump(mode="json")) == event


def test_parse_event_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        parse_event({"type": "mystery", "run_id": "1", "agent": "a"})


def test_emitters_satisfy_protocol() -> None:
    assert isinstance(NullEventEmitter(), EventEmitter)
    assert isinstance(CollectingEventEmitter(), EventEmitter)
    assert isinstance(QueueEventEmitter(), EventEmitter)


async def test_collecting_emitter() -> None:
    collector = CollectingEventEmitter()
    await NullEventEmitter().emit(TokenStream(run_id="1", agent="a", token="x"))
    await collector.emit(TokenStream(run_id="1", agent="a", token="x"))
    assert len(collector.events) == 1
    collector.clear()
    assert collector.events == []


async def test_queue_emitter_relays_in_order_and_forwards_downstream() -> None:
    downstream = CollectingEventEmitter()
    relay = QueueEventEmitter(downstream=downstream)

    async def produce() -> None:
        for token in ("a", "b", "c"):
            await relay.emit(TokenStream(run_id="1", agent="a", token=token))
            await asyncio.sleep(0)
        relay.close()
        relay.close()  # idempotent
        await relay.emit(TokenStream(run_id="1", agent="a", token="late"))

    producer = asyncio.create_task(produce())
    received = [event async for event in relay]
    await producer
    assert [e.token for e in received if isinstance(e, TokenStream)] == ["a", "b", "c"]
    assert [e.token for e in downstream.events if isinstance(e, TokenStream)] == [
        "a",
        "b",
        "c",
        "late",
    ]
    assert relay.closed
