import logging
import sys

import structlog

from .config import settings


_configured = False

_SECRET_KEYS = {"x-llm-key", "api_key", "llm_key", "authorization", "x_llm_key"}


def redact_llm_keys(_logger, _method, event_dict):
    for k in list(event_dict):
        if str(k).lower() in _SECRET_KEYS:
            event_dict[k] = "***"
    return event_dict


def _configure() -> None:
    global _configured
    if _configured:
        return

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=level,
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            redact_llm_keys,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    _configure()
    return structlog.get_logger(name)
