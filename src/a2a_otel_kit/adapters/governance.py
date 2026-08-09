"""Opt-in adapter that delivers sanitized structured events to AI Governance."""

from __future__ import annotations

import asyncio
import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from http.client import HTTPConnection, HTTPSConnection
from typing import Protocol
from urllib.parse import urlparse
from uuid import UUID, uuid4

from opentelemetry import trace

from a2a_otel_kit.domain.attributes import (
    AttributeValue,
    StructuredEvent,
    sanitize_attributes,
)

_EVENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_MAX_EVENT_NAME_LENGTH = 200
_MAX_BOUNDED_STRING_LENGTH = 256
_MAX_CREDENTIAL_LENGTH = 1024
_RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


class RuntimeTelemetryCredentialProvider(Protocol):
    """Resolve the per-Agent Governance telemetry credential."""

    def __call__(self) -> str:
        """Return the current machine credential without logging it."""
        ...


class GovernanceRuntimeTelemetryError(RuntimeError):
    """Base class for sanitized Governance sink failures."""


class GovernanceRuntimeTelemetryContractError(GovernanceRuntimeTelemetryError):
    """Raised when a structured event cannot satisfy the Governance contract."""


class GovernanceRuntimeTelemetryDeliveryError(GovernanceRuntimeTelemetryError):
    """Raised when the event cannot be delivered within the configured policy."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        """Build a content-free delivery failure."""
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class GovernanceRuntimeTelemetrySettings:
    """Non-secret configuration for the Governance runtime-telemetry sink."""

    base_url: str
    agent_id: str
    service: str
    environment: str
    version: str
    timeout_seconds: float = 2.0
    max_attempts: int = 3
    backoff_base_seconds: float = 0.1

    def __post_init__(self) -> None:
        """Validate transport and bounded contract settings eagerly."""
        parsed = urlparse(self.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("base_url must be an absolute HTTP(S) URL without credentials/query")
        host = (parsed.hostname or "").lower()
        if parsed.scheme == "http" and host not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("remote Governance runtime telemetry requires HTTPS")
        try:
            agent_id = UUID(self.agent_id)
        except ValueError as exc:
            raise ValueError("agent_id must be a UUID") from exc
        if agent_id.int == 0 or str(agent_id) != self.agent_id:
            raise ValueError("agent_id must be a canonical non-nil UUID")
        for name, value in (
            ("service", self.service),
            ("environment", self.environment),
            ("version", self.version),
        ):
            _require_bounded_string(name, value)
        if not 0 < self.timeout_seconds <= 10:
            raise ValueError("timeout_seconds must be > 0 and <= 10")
        if not 1 <= self.max_attempts <= 5:
            raise ValueError("max_attempts must be between 1 and 5")
        if not 0 <= self.backoff_base_seconds <= 5:
            raise ValueError("backoff_base_seconds must be between 0 and 5")


@dataclass(frozen=True, slots=True)
class GovernanceRuntimeTelemetryEnvelope:
    """Prepared content-free event that can be retried without changing identity."""

    payload: Mapping[str, object]

    @property
    def event_id(self) -> str:
        """Return the prepared event identifier."""
        return str(self.payload["event_id"])


@dataclass(frozen=True, slots=True)
class GovernanceRuntimeTelemetryReceipt:
    """Successful delivery metadata with no credential or response payload."""

    event_id: str
    attempts: int
    status_code: int


Transport = Callable[[str, bytes, Mapping[str, str], float], int]
Clock = Callable[[], datetime]
IdFactory = Callable[[], str]


class GovernanceRuntimeTelemetrySink:
    """Prepare and deliver privacy-safe structured events to Governance."""

    def __init__(
        self,
        settings: GovernanceRuntimeTelemetrySettings,
        credential_provider: RuntimeTelemetryCredentialProvider,
        *,
        transport: Transport | None = None,
        clock: Clock | None = None,
        id_factory: IdFactory | None = None,
    ) -> None:
        """Initialize the adapter without resolving secret material or doing I/O."""
        self._settings = settings
        self._credential_provider = credential_provider
        self._transport = transport or _post
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda: str(uuid4()))

    def prepare(self, event: StructuredEvent) -> GovernanceRuntimeTelemetryEnvelope:
        """Re-sanitize and map one structured event into the closed Governance contract."""
        observed_at = self._clock()
        if observed_at.tzinfo is None or observed_at.utcoffset() != UTC.utcoffset(observed_at):
            raise GovernanceRuntimeTelemetryContractError("clock must return a UTC timestamp")
        event_id = self._id_factory()
        try:
            parsed_event_id = UUID(event_id)
        except ValueError as exc:
            raise GovernanceRuntimeTelemetryContractError(
                "event id factory must return a UUID"
            ) from exc
        if parsed_event_id.int == 0 or str(parsed_event_id) != event_id:
            raise GovernanceRuntimeTelemetryContractError(
                "event id factory must return a canonical non-nil UUID"
            )
        if (
            not event.event_name
            or len(event.event_name) > _MAX_EVENT_NAME_LENGTH
            or _EVENT_NAME_PATTERN.fullmatch(event.event_name) is None
        ):
            raise GovernanceRuntimeTelemetryContractError(
                "event_name is incompatible with the Governance telemetry contract"
            )

        attributes = sanitize_attributes(event.attributes)
        trace_id, span_id = _active_span_ids()
        payload: dict[str, object] = {
            "schema_version": "1.0",
            "source_schema_version": event.schema_version,
            "event_id": event_id,
            "observed_at": observed_at.isoformat(),
            "event_name": event.event_name,
            "event_outcome": event.event_outcome.value,
            "service": self._settings.service,
            "environment": self._settings.environment,
            "version": self._settings.version,
        }
        _put(payload, "trace_id", trace_id)
        _put(payload, "span_id", span_id)
        _put_bounded(payload, "component", attributes.get("component"))
        _put_bounded(payload, "operation", attributes.get("operation"))
        _put_bounded(payload, "correlation_id", attributes.get("correlation_id"))
        _put_bounded(payload, "request_id", attributes.get("request_id"))
        _put_retry_count(payload, attributes.get("retry_count"))
        _put_duration(payload, attributes.get("duration_ms"))
        _put_http_method(payload, attributes.get("http.method"))
        _put_http_status(payload, attributes.get("http.status_code"))
        _put_bounded(payload, "error_type", attributes.get("error.type"))
        return GovernanceRuntimeTelemetryEnvelope(payload=payload)

    async def deliver(
        self,
        envelope: GovernanceRuntimeTelemetryEnvelope,
    ) -> GovernanceRuntimeTelemetryReceipt:
        """Deliver a prepared envelope, retrying transient failures with stable identity."""
        credential = _resolve_credential(self._credential_provider)
        body = _encode_payload(envelope.payload)
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Telemetry-Api-Key": credential,
        }
        endpoint = (
            f"{self._settings.base_url.rstrip('/')}/api/v1/agents/"
            f"{self._settings.agent_id}/runtime-telemetry"
        )

        last_status: int | None = None
        for attempt in range(1, self._settings.max_attempts + 1):
            try:
                status_code = await asyncio.to_thread(
                    self._transport,
                    endpoint,
                    body,
                    headers,
                    self._settings.timeout_seconds,
                )
            except (OSError, TimeoutError):
                status_code = None
            if status_code == 202:
                return GovernanceRuntimeTelemetryReceipt(
                    event_id=envelope.event_id,
                    attempts=attempt,
                    status_code=status_code,
                )
            last_status = status_code
            if status_code is not None and status_code not in _RETRYABLE_STATUS_CODES:
                raise GovernanceRuntimeTelemetryDeliveryError(
                    "Governance rejected runtime telemetry",
                    status_code=status_code,
                )
            if attempt < self._settings.max_attempts:
                await asyncio.sleep(self._settings.backoff_base_seconds * (2 ** (attempt - 1)))

        raise GovernanceRuntimeTelemetryDeliveryError(
            "Governance runtime telemetry delivery exhausted retries",
            status_code=last_status,
        )

    async def emit(
        self,
        event: StructuredEvent,
    ) -> GovernanceRuntimeTelemetryReceipt:
        """Prepare and deliver one event using a stable ID across internal retries."""
        return await self.deliver(self.prepare(event))


def _resolve_credential(provider: RuntimeTelemetryCredentialProvider) -> str:
    try:
        credential = provider()
    except Exception:
        raise GovernanceRuntimeTelemetryDeliveryError(
            "Runtime telemetry credential provider failed"
        ) from None
    if (
        not isinstance(credential, str)
        or not credential
        or len(credential) > _MAX_CREDENTIAL_LENGTH
        or "\r" in credential
        or "\n" in credential
    ):
        raise GovernanceRuntimeTelemetryDeliveryError(
            "Runtime telemetry credential provider returned an invalid credential"
        )
    return credential


def _encode_payload(payload: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(
            payload,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise GovernanceRuntimeTelemetryContractError(
            "Runtime telemetry payload is not JSON-safe"
        ) from exc


def _active_span_ids() -> tuple[str | None, str | None]:
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None, None
    return (
        format(span_context.trace_id, "032x"),
        format(span_context.span_id, "016x"),
    )


def _put(payload: dict[str, object], key: str, value: object | None) -> None:
    if value is not None:
        payload[key] = value


def _put_bounded(
    payload: dict[str, object],
    key: str,
    value: AttributeValue | None,
) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise GovernanceRuntimeTelemetryContractError(f"{key} must be a string")
    _require_bounded_string(key, value)
    payload[key] = value


def _put_retry_count(payload: dict[str, object], value: AttributeValue | None) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1000:
        raise GovernanceRuntimeTelemetryContractError(
            "retry_count must be an integer from 0 to 1000"
        )
    payload["retry_count"] = value


def _put_duration(payload: dict[str, object], value: AttributeValue | None) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GovernanceRuntimeTelemetryContractError("duration_ms must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric) or not 0 <= numeric <= 86_400_000:
        raise GovernanceRuntimeTelemetryContractError(
            "duration_ms must be finite and between 0 and 86400000"
        )
    payload["duration_ms"] = numeric


def _put_http_method(payload: dict[str, object], value: AttributeValue | None) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not 1 <= len(value) <= 16:
        raise GovernanceRuntimeTelemetryContractError("http.method must be a string up to 16 chars")
    payload["http_method"] = value


def _put_http_status(payload: dict[str, object], value: AttributeValue | None) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or not 100 <= value <= 599:
        raise GovernanceRuntimeTelemetryContractError(
            "http.status_code must be an integer from 100 to 599"
        )
    payload["http_status_code"] = value


def _require_bounded_string(name: str, value: str) -> None:
    if not value or len(value) > _MAX_BOUNDED_STRING_LENGTH:
        raise ValueError(f"{name} must be a non-empty string up to 256 characters")


def _post(
    endpoint: str,
    body: bytes,
    headers: Mapping[str, str],
    timeout_seconds: float,
) -> int:
    """POST one telemetry envelope without reading the response body."""
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise GovernanceRuntimeTelemetryContractError(
            "Prepared Governance endpoint must use HTTP(S)"
        )

    connection_type = HTTPSConnection if parsed.scheme == "https" else HTTPConnection
    connection = connection_type(
        parsed.hostname,
        port=parsed.port,
        timeout=timeout_seconds,
    )
    path = parsed.path or "/"

    try:
        connection.request(
            "POST",
            path,
            body=body,
            headers=dict(headers),
        )
        response = connection.getresponse()
        try:
            return int(response.status)
        finally:
            response.close()
    finally:
        connection.close()
