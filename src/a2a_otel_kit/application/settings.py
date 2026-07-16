"""Immutable, validated observability settings.

``ObservabilitySettings`` carries no credential or secret fields, so its default representation
never needs redaction - printing or logging a settings instance is always safe. Values may be
supplied explicitly by the caller or loaded from ``A2A_OTEL_``-prefixed environment variables;
either way, nothing is read until a caller explicitly constructs an instance, so importing this
module performs no I/O.
"""

from typing import Literal, Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from a2a_otel_kit.domain.errors import InvalidObservabilityConfigurationError


class ObservabilitySettings(BaseSettings):
    """Validated configuration for one process's observability setup.

    Frozen after construction: use :meth:`model_copy` to derive a variant rather than mutating an
    existing instance in place.
    """

    model_config = SettingsConfigDict(frozen=True, extra="forbid", env_prefix="A2A_OTEL_")

    service_name: str
    service_version: str
    environment: str
    enabled: bool = False
    otlp_endpoint: str | None = None
    otlp_timeout_seconds: float = 10.0
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    @field_validator("service_name", "service_version", "environment")
    @classmethod
    def _require_non_blank(cls, value: str) -> str:
        """Reject blank identifiers; an empty service name breaks resource attribution."""
        if not value.strip():
            raise InvalidObservabilityConfigurationError(
                "service_name, service_version, and environment must be non-empty"
            )
        return value

    @field_validator("otlp_endpoint")
    @classmethod
    def _require_http_scheme(cls, value: str | None) -> str | None:
        """Reject an endpoint that is not an HTTP(S) URL; the OTLP HTTP exporter requires one."""
        if value is not None and not (value.startswith("http://") or value.startswith("https://")):
            raise InvalidObservabilityConfigurationError(
                f"otlp_endpoint must start with http:// or https://, got: {value!r}"
            )
        return value

    @field_validator("otlp_timeout_seconds")
    @classmethod
    def _require_positive_timeout(cls, value: float) -> float:
        """Reject a non-positive timeout; it would make every export attempt fail immediately."""
        if value <= 0:
            raise InvalidObservabilityConfigurationError("otlp_timeout_seconds must be positive")
        return value

    @model_validator(mode="after")
    def _require_endpoint_when_enabled(self) -> Self:
        """Enforce that an enabled configuration always has somewhere to export spans to."""
        if self.enabled and self.otlp_endpoint is None:
            raise InvalidObservabilityConfigurationError(
                "otlp_endpoint is required when enabled=True"
            )
        return self
