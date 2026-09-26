"""Example workflow: two :class:`ExampleAgent` steps in sequence."""

from __future__ import annotations

import logging

from agents.implementations.example_agent import ExampleAgent
from agents.workflows.base import SequentialWorkflow

logger = logging.getLogger(__name__)

EXAMPLE_WORKFLOW_NAME = "example_workflow"
EXAMPLE_WORKFLOW_DESCRIPTION = (
    "Runs the example agent twice; the second call processes the first result."
)


def build_example_workflow() -> SequentialWorkflow:
    """Build the ``example_workflow`` agent (``"hi"`` → ``"Processed: Processed: hi"``)."""
    return SequentialWorkflow(
        [ExampleAgent(), ExampleAgent()],
        name=EXAMPLE_WORKFLOW_NAME,
        description=EXAMPLE_WORKFLOW_DESCRIPTION,
    )
