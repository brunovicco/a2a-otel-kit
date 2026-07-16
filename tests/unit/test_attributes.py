"""Tests for privacy-safe attribute sanitization and the structured-event schema."""

import pytest

from a2a_otel_kit.domain.attributes import (
    MAX_ATTRIBUTE_STRING_LENGTH,
    STRUCTURED_EVENT_SCHEMA_VERSION,
    StructuredEvent,
    StructuredEventOutcome,
    is_sensitive_key,
    sanitize_attributes,
)
from a2a_otel_kit.domain.errors import InvalidStructuredEventError


def test_sanitize_attributes_keeps_only_allowlisted_keys() -> None:
    """An unknown key is dropped even though its value is otherwise safe."""
    result = sanitize_attributes({"service": "billing", "not_allowlisted": "value"})

    assert result == {"service": "billing"}


def test_sanitize_attributes_extends_allowlist_per_call() -> None:
    """extra_allowed_keys widens the allowlist without weakening the default one."""
    result = sanitize_attributes(
        {"service": "billing", "workflow_id": "wf-1"},
        extra_allowed_keys=frozenset({"workflow_id"}),
    )

    assert result == {"service": "billing", "workflow_id": "wf-1"}


@pytest.mark.parametrize(
    "key",
    ["password", "api_key", "api-key", "Authorization", "cookie", "secret_token", "PRIVATE_KEY"],
)
def test_sanitize_attributes_redacts_sensitive_keys_even_if_allowlisted(key: str) -> None:
    """A sensitive-looking key is dropped even when explicitly added to the allowlist."""
    result = sanitize_attributes(
        {key: "must-not-leave-process"}, extra_allowed_keys=frozenset({key})
    )

    assert result == {}


def test_sanitize_attributes_drops_nested_and_oversized_values() -> None:
    """Nested structures and oversized strings are dropped; scalars within bounds survive."""
    result = sanitize_attributes(
        {
            "service": "billing",
            "operation": {"nested": "object"},
            "component": ["a", "list"],
            "outcome": "x" * (MAX_ATTRIBUTE_STRING_LENGTH + 1),
            "retry_count": 2,
        }
    )

    assert result == {"service": "billing", "retry_count": 2}


def test_sanitize_attributes_handles_none_input() -> None:
    """A missing attributes mapping sanitizes to an empty dict, not an error."""
    assert sanitize_attributes(None) == {}


@pytest.mark.parametrize("key", ["password", "OTLP_API_KEY", "session_token"])
def test_is_sensitive_key_matches_credential_shaped_names(key: str) -> None:
    """The public sensitive-key predicate agrees with the redaction it backs."""
    assert is_sensitive_key(key) is True


def test_is_sensitive_key_does_not_match_ordinary_names() -> None:
    """An ordinary allowlisted-style key is not flagged as sensitive."""
    assert is_sensitive_key("service") is False


def test_structured_event_carries_schema_version_and_outcome() -> None:
    """A constructed event always carries the current schema version."""
    event = StructuredEvent(
        event_name="workflow.started", event_outcome=StructuredEventOutcome.SUCCESS
    )

    assert event.schema_version == STRUCTURED_EVENT_SCHEMA_VERSION
    assert event.event_outcome is StructuredEventOutcome.SUCCESS


def test_structured_event_rejects_blank_event_name() -> None:
    """An event with no name would break the logging contract and must not be constructed."""
    with pytest.raises(InvalidStructuredEventError):
        StructuredEvent(event_name="   ", event_outcome=StructuredEventOutcome.ERROR)
