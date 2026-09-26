"""python -m agents (run in a subprocess so the entry point is exercised for real)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "agents", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=120,
        check=False,
    )


def test_cli_prints_result_json(tmp_path: Path) -> None:
    completed = _run("hello", cwd=tmp_path)
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["response"] == "Processed: hello"
    assert payload["agent"] == "example"
    assert payload["metadata"]["tools_used"] == ["word_count"]
    assert "run_id" in payload["metadata"]


def test_cli_stream_prints_one_json_line_per_event(tmp_path: Path) -> None:
    completed = _run("hello there", "--stream", "--agent", "example", cwd=tmp_path)
    assert completed.returncode == 0, completed.stderr
    events = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    assert [event["type"] for event in events] == [
        "agent_started",
        "tool_started",
        "tool_completed",
        "agent_completed",
    ]
    assert events[-1]["result"]["response"] == "Processed: hello there"


def test_cli_unknown_agent_exits_1(tmp_path: Path) -> None:
    completed = _run("hello", "--agent", "nope", cwd=tmp_path)
    assert completed.returncode == 1
    assert "Unknown agent 'nope'" in completed.stderr
    assert completed.stdout == ""


def test_cli_list_agents(tmp_path: Path) -> None:
    completed = _run("--list", cwd=tmp_path)
    assert completed.returncode == 0, completed.stderr
    names = [entry["name"] for entry in json.loads(completed.stdout)]
    assert names == ["example", "example_workflow"]


def test_cli_missing_message_is_usage_error(tmp_path: Path) -> None:
    completed = _run(cwd=tmp_path)
    assert completed.returncode == 2
    assert "message is required" in completed.stderr
