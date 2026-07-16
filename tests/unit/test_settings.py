"""Tests for validated, immutable observability settings."""

import pytest
from pydantic import ValidationError

from a2a_otel_kit.application.settings import ObservabilitySettings
from a2a_otel_kit.domain.attributes import is_sensitive_key
from a2a_otel_kit.domain.errors import InvalidObservabilityConfigurationError


def _settings(**overrides: object) -> ObservabilitySettings:
    defaults: dict[str, object] = {
        "service_name": "billing",
        "service_version": "1.2.3",
        "environment": "test",
    }
    defaults.update(overrides)
    return ObservabilitySettings(**defaults)  # type: ignore[arg-type]


def test_disabled_settings_do_not_require_an_otlp_endpoint() -> None:
    """Disabled/no-op mode never requires exporter configuration."""
    settings = _settings()

    assert settings.enabled is False
    assert settings.otlp_endpoint is None


def test_enabled_settings_accept_a_valid_otlp_endpoint() -> None:
    """Enabling tracing with a valid HTTP endpoint is accepted."""
    settings = _settings(enabled=True, otlp_endpoint="http://localhost:4318")

    assert settings.enabled is True
    assert settings.otlp_endpoint == "http://localhost:4318"


def test_enabled_without_endpoint_is_rejected_before_any_provider_exists() -> None:
    """Enabling tracing without an endpoint is invalid configuration, not a runtime surprise."""
    with pytest.raises(InvalidObservabilityConfigurationError, match="otlp_endpoint"):
        _settings(enabled=True)


def test_blank_service_name_is_rejected() -> None:
    """A blank identifier is rejected rather than silently accepted."""
    with pytest.raises(InvalidObservabilityConfigurationError):
        _settings(service_name="   ")


def test_non_http_endpoint_is_rejected() -> None:
    """An endpoint without an HTTP(S) scheme is rejected."""
    with pytest.raises(InvalidObservabilityConfigurationError, match="http"):
        _settings(enabled=True, otlp_endpoint="localhost:4318")


def test_non_positive_timeout_is_rejected() -> None:
    """A zero or negative timeout would make every export attempt fail immediately."""
    with pytest.raises(InvalidObservabilityConfigurationError):
        _settings(otlp_timeout_seconds=0)


def test_settings_are_frozen() -> None:
    """Settings are immutable once constructed."""
    settings = _settings()

    with pytest.raises(ValidationError):
        settings.service_name = "other"  # type: ignore[misc]


def test_settings_reject_unknown_fields() -> None:
    """An unexpected field is rejected rather than silently ignored."""
    with pytest.raises(ValidationError):
        _settings(unexpected_field="value")


def test_settings_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings may be sourced from A2A_OTEL_-prefixed environment variables."""
    monkeypatch.setenv("A2A_OTEL_SERVICE_NAME", "billing")
    monkeypatch.setenv("A2A_OTEL_SERVICE_VERSION", "9.9.9")
    monkeypatch.setenv("A2A_OTEL_ENVIRONMENT", "staging")

    settings = ObservabilitySettings()

    assert settings.service_name == "billing"
    assert settings.environment == "staging"


def test_no_settings_field_is_named_like_a_credential() -> None:
    """This settings model carries no secret-shaped field, so its repr can never leak one.

    A future field named e.g. ``otlp_api_key`` would fail this test immediately, flagging that it
    needs deliberate repr/log redaction before being added.
    """
    for field_name in ObservabilitySettings.model_fields:
        assert not is_sensitive_key(field_name), f"unexpected credential-shaped field: {field_name}"
