"""Structured logging bootstrap.

Call :func:`configure_logging` once, at process startup, before any other code emits a log line.
Renders JSON to stdout by default; pass ``log_format="console"`` for a human-readable renderer
during local development. Every log event automatically carries ``trace_id``/``span_id`` when a
valid OpenTelemetry span is active - callers never bind those manually. Never log secrets,
personal data, prompts, or model responses - see ``.claude/rules/security-privacy.md``.
"""

import logging
import sys
from collections.abc import MutableMapping
from typing import Literal

import structlog
from opentelemetry.trace import get_current_span


def _inject_active_span_context(
    _logger: object, _method_name: str, event_dict: MutableMapping[str, object]
) -> MutableMapping[str, object]:
    """Add ``trace_id``/``span_id`` to a log event when a valid span is currently active."""
    span_context = get_current_span().get_span_context()
    if span_context.is_valid:
        event_dict["trace_id"] = format(span_context.trace_id, "032x")
        event_dict["span_id"] = format(span_context.span_id, "016x")
    return event_dict


def configure_logging(
    *,
    service: str,
    environment: str,
    version: str,
    log_level: str = "INFO",
    log_format: Literal["json", "console"] = "json",
) -> None:
    """Configure structlog and standard-library logging for this process."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        _inject_active_span_context,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    renderer = (
        structlog.processors.JSONRenderer()
        if log_format == "json"
        else structlog.dev.ConsoleRenderer()
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(level)

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        service=service, environment=environment, version=version
    )


def bind_correlation_id(correlation_id: str) -> None:
    """Bind a correlation identifier to the current logging context."""
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)


def clear_request_context() -> None:
    """Clear per-request context variables without dropping process-wide fields.

    Removes only ``correlation_id``. Using :func:`structlog.contextvars.clear_contextvars` here
    would also drop the ``service``/``environment``/``version`` fields bound once at startup by
    :func:`configure_logging`, silently dropping them from every log line for the rest of the
    process. ``trace_id``/``span_id`` are never bound as contextvars in the first place - they are
    read live from the active OpenTelemetry span on every log call - so there is nothing to clear.
    """
    structlog.contextvars.unbind_contextvars("correlation_id")
