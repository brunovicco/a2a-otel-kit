"""Privacy-safe telemetry attributes and the versioned structured-event schema.

Pure Python: no OpenTelemetry, structlog, or Pydantic import. This module is the single place
that decides which attribute keys and values are safe to leave the process as telemetry. It is
deny-by-default: only allowlisted, scalar, bounded values survive, and a fixed set of
sensitive-looking key patterns is rejected even if a caller (or an attacker-controlled attribute
dict) tries to allowlist them explicitly.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from a2a_otel_kit.domain.errors import InvalidStructuredEventError

type AttributeValue = str | int | float | bool | None

STRUCTURED_EVENT_SCHEMA_VERSION = 1
MAX_ATTRIBUTE_STRING_LENGTH = 256

DEFAULT_ALLOWED_ATTRIBUTE_KEYS: frozenset[str] = frozenset(
    {
        "service",
        "environment",
        "version",
        "component",
        "operation",
        "outcome",
        "correlation_id",
        "request_id",
        "retry_count",
        "duration_ms",
        "http.method",
        "http.status_code",
        "error.type",
    }
)

_SENSITIVE_KEY_PATTERN = re.compile(
    r"(password|secret|token|authoriz|cookie|api[_-]?key|credential|private[_-]?key"
    r"|ssn|social[_-]?security|access[_-]?key)",
    re.IGNORECASE,
)


def is_sensitive_key(key: str) -> bool:
    """Return True when a key looks like it names a credential or secret.

    Used both to redact attributes deterministically in :func:`sanitize_attributes` and, in
    tests, to assert that this library's own configuration models never expose a field shaped
    like a credential.
    """
    return bool(_SENSITIVE_KEY_PATTERN.search(key))


def sanitize_attributes(
    attributes: Mapping[str, object] | None,
    *,
    extra_allowed_keys: frozenset[str] = frozenset(),
) -> dict[str, AttributeValue]:
    """Return only allowlisted, scalar, bounded attributes from an untrusted mapping.

    Treats ``attributes`` as untrusted input. A key survives only if it is present in the merged
    allowlist (:data:`DEFAULT_ALLOWED_ATTRIBUTE_KEYS` plus ``extra_allowed_keys``), does not match
    :data:`_SENSITIVE_KEY_PATTERN`, and its value is a scalar (``str | int | float | bool | None``)
    within :data:`MAX_ATTRIBUTE_STRING_LENGTH` for strings. Everything else - unknown keys, nested
    structures, oversized strings, and sensitive-looking keys - is silently dropped.
    """
    allowed_keys = DEFAULT_ALLOWED_ATTRIBUTE_KEYS | extra_allowed_keys
    sanitized: dict[str, AttributeValue] = {}
    for key, value in (attributes or {}).items():
        if key not in allowed_keys:
            continue
        if is_sensitive_key(key):
            continue
        if isinstance(value, bool) or value is None:
            sanitized[key] = value
            continue
        if isinstance(value, (int, float)):
            sanitized[key] = value
            continue
        if isinstance(value, str):
            if len(value) > MAX_ATTRIBUTE_STRING_LENGTH:
                continue
            sanitized[key] = value
    return sanitized


class StructuredEventOutcome(StrEnum):
    """Closed set of outcomes a structured event may report."""

    STARTED = "started"
    SUCCESS = "success"
    FAILURE = "failure"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class StructuredEvent:
    """A single versioned structured-log event.

    ``event_name`` and ``event_outcome`` are required so that free-text log messages are never the
    only machine-readable content of an event, matching this library's logging contract.
    """

    event_name: str
    event_outcome: StructuredEventOutcome
    attributes: Mapping[str, AttributeValue] = field(default_factory=dict)
    schema_version: int = field(default=STRUCTURED_EVENT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        """Reject an event with no name; a nameless event breaks the logging contract."""
        if not self.event_name.strip():
            raise InvalidStructuredEventError("event_name must be a non-empty string")
