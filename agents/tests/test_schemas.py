"""AgentRequest / AgentResult / AgentInfo / Message validation."""

from __future__ import annotations

from datetime import UTC

import pytest
from pydantic import ValidationError

from agents.schemas.agent import AgentInfo, AgentRequest, AgentResult
from agents.schemas.messages import Message


def test_request_rejects_empty_message() -> None:
    with pytest.raises(ValidationError):
        AgentRequest(message="")


def test_request_metadata_default_is_a_fresh_dict() -> None:
    first = AgentRequest(message="a")
    second = AgentRequest(message="b")
    assert first.metadata == {}
    assert first.metadata is not second.metadata
    first.metadata["k"] = 1
    assert second.metadata == {}


def test_request_defaults_and_roundtrip() -> None:
    request = AgentRequest(message="hi", conversation_id="c1", metadata={"source": "test"})
    assert request.conversation_id == "c1"
    assert AgentRequest.model_validate(request.model_dump()) == request


def test_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        AgentRequest.model_validate({"message": "hi", "agent": "example"})


def test_result_requires_response_and_agent() -> None:
    with pytest.raises(ValidationError):
        AgentResult.model_validate({"response": "x"})
    result = AgentResult(response="x", agent="example")
    assert result.metadata == {}
    assert result.metadata is not AgentResult(response="y", agent="example").metadata


def test_agent_info_defaults() -> None:
    assert AgentInfo(name="example").description == ""


def test_message_has_utc_timestamp_and_role_validation() -> None:
    message = Message(role="user", content="hi")
    assert message.timestamp.tzinfo is UTC
    assert message.metadata == {}
    with pytest.raises(ValidationError):
        Message.model_validate({"role": "robot", "content": "hi"})
