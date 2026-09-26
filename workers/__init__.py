"""Menu Hero Core — background workers (reserved, nothing runs here yet).

This directory is the future home of the worker package that will consume
queued agent jobs and execute them through ``agents.run_agent`` — the same
entry point the FastAPI backend calls in-process today.

The swap point on the backend side is the ``AgentExecutor`` protocol in
``backend/app/services/agent_service.py``: the HTTP layer will keep calling
``AgentService``, only the executor implementation changes from in-process to
queue-backed. See ``workers/README.md`` for the intended architecture and the
invariants every implementation must respect.
"""
