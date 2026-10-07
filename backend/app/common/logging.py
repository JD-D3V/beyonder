import logging
import sys

import structlog

from .config import settings


_configured = False

_SECRET_KEYS = {
    "x-llm-key", "api_key", "llm_key", "authorization", "x_llm_key",
    "password", "token",
}


_MAX_REDACT_DEPTH = 8


def _redact(value, _depth: int = 0):
    if isinstance(value, (dict, list, tuple)) and _depth >= _MAX_REDACT_DEPTH:
        return f"<{type(value).__name__}…>"
    if isinstance(value, dict):
        return {
            k: "***" if str(k).lower() in _SECRET_KEYS else _redact(v, _depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v, _depth + 1) for v in value]
    if isinstance(value, tuple):
        return tuple(_redact(v, _depth + 1) for v in value)
    return value


def redact_llm_keys(_logger, _method, event_dict):
    return _redact(event_dict)


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
