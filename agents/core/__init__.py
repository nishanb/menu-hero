"""Core runtime of the agents package: base agent, context, events, registry, runner.

This package intentionally has no re-exports so that sub-modules can import each other
without cycles. Import from the concrete modules (``agents.core.agent`` ...) or from the
top-level ``agents`` package, which re-exports the public API.
"""
