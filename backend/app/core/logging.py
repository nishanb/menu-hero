"""Process-wide logging configuration.

:func:`setup_logging` installs one stderr handler with a consistent format on the root
logger and routes the uvicorn loggers through it, so application, framework and access
logs look the same. It is idempotent: calling it again only updates the level.
"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)

HANDLER_NAME = "menu_hero"
LOG_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
UVICORN_LOGGERS: tuple[str, ...] = ("uvicorn", "uvicorn.error", "uvicorn.access")


def _root_handler(root: logging.Logger) -> logging.Handler | None:
    """Return the handler installed by a previous :func:`setup_logging` call, if any."""
    for handler in root.handlers:
        if handler.get_name() == HANDLER_NAME:
            return handler
    return None


def setup_logging(level: str | int = "INFO") -> None:
    """Configure the root and uvicorn loggers with one handler and format.

    ``level`` is a standard logging level name (``"INFO"``) or number. Safe to call more
    than once (per worker process, in tests, ...): the handler is installed only once.
    """
    root = logging.getLogger()
    handler = _root_handler(root)
    if handler is None:
        handler = logging.StreamHandler(sys.stderr)
        handler.set_name(HANDLER_NAME)
        handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        root.addHandler(handler)
    root.setLevel(level)

    # uvicorn installs its own handlers (and disables propagation) via dictConfig before
    # the app is imported; funnel its loggers through the root handler instead.
    for name in UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
        uvicorn_logger.setLevel(logging.NOTSET)

    logger.debug("logging configured at level %s", logging.getLevelName(root.level))
