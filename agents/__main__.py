"""Command-line entry point: ``python -m agents "hello" [--agent NAME] [--stream]``.

Prints the :class:`AgentResult` as JSON, or one JSON line per event with ``--stream``.
Exit codes: 0 success, 1 agent error (message on stderr), 2 invalid arguments.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence

from pydantic import ValidationError

from agents.core.events import AgentFailed
from agents.core.exceptions import AgentError
from agents.core.registry import get_default_registry
from agents.core.runner import run_agent, stream_agent
from agents.schemas.agent import AgentRequest

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        prog="python -m agents", description="Run a Menu Hero agent from the command line."
    )
    parser.add_argument("message", nargs="?", default=None, help="The message to send.")
    parser.add_argument("--agent", default="example", help="Registered agent name.")
    parser.add_argument(
        "--stream", action="store_true", help="Print one JSON line per event instead of the result."
    )
    parser.add_argument(
        "--timeout", type=float, default=None, help="Seconds before the run is aborted."
    )
    parser.add_argument("--list", action="store_true", help="List registered agents and exit.")
    parser.add_argument(
        "--log-level", default=None, help="Enable logging to stderr at this level (e.g. DEBUG)."
    )
    return parser


async def _run_stream(request: AgentRequest, agent_name: str) -> bool:
    """Print every event as a JSON line; return True when the run completed successfully."""
    succeeded = True
    async for event in stream_agent(request, agent_name=agent_name):
        print(event.model_dump_json())
        if isinstance(event, AgentFailed):
            succeeded = False
    return succeeded


def _list_agents() -> int:
    infos = get_default_registry().describe()
    print("[" + ", ".join(info.model_dump_json() for info in infos) + "]")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.log_level:
        logging.basicConfig(level=args.log_level.upper(), stream=sys.stderr)
    if args.list:
        return _list_agents()
    if args.message is None:
        parser.error("a message is required (or use --list)")

    try:
        request = AgentRequest(message=args.message)
    except ValidationError as exc:
        print(f"error: invalid message: {exc.errors()[0]['msg']}", file=sys.stderr)
        return 2

    try:
        if args.stream:
            return 0 if asyncio.run(_run_stream(request, args.agent)) else 1
        result = asyncio.run(run_agent(request, agent_name=args.agent, timeout=args.timeout))
    except AgentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
