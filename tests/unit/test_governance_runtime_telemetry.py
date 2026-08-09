import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime

import pytest

from a2a_otel_kit.adapters.governance import (
    GovernanceRuntimeTelemetryContractError,
    GovernanceRuntimeTelemetryDeliveryError,
    GovernanceRuntimeTelemetrySettings,
    GovernanceRuntimeTelemetrySink,
)
from a2a_otel_kit.domain.attributes import (
    AttributeValue,
    StructuredEvent,
    StructuredEventOutcome,
)


def settings() -> GovernanceRuntimeTelemetrySettings:
    return GovernanceRuntimeTelemetrySettings(
        base_url="http://127.0.0.1:8000",
        agent_id="11111111-1111-4111-8111-111111111111",
        service="decisao-agent",
        environment="test",
        version="1.2.3",
        timeout_seconds=1,
        max_attempts=3,
        backoff_base_seconds=0,
    )


def event(**attributes: AttributeValue) -> StructuredEvent:
    return StructuredEvent(
        event_name="a2a.client.send_message.completed",
        event_outcome=StructuredEventOutcome.SUCCESS,
        attributes=attributes,
    )


def test_prepare_maps_only_closed_sanitized_contract() -> None:
    sink = GovernanceRuntimeTelemetrySink(
        settings(),
        lambda: "secret",
        clock=lambda: datetime(2026, 8, 8, 22, 30, tzinfo=UTC),
        id_factory=lambda: "22222222-2222-4222-8222-222222222222",
    )

    extra_attributes: dict[str, AttributeValue] = {
        "http.method": "POST",
        "http.status_code": 202,
        "authorization": "must-not-leave-process",
        "prompt": "must-not-leave-process",
    }

    envelope = sink.prepare(
        event(
            operation="send_message",
            correlation_id="corr-1",
            duration_ms=12.5,
            **extra_attributes,
        )
    )

    assert envelope.payload == {
        "schema_version": "1.0",
        "source_schema_version": 1,
        "event_id": "22222222-2222-4222-8222-222222222222",
        "observed_at": "2026-08-08T22:30:00+00:00",
        "event_name": "a2a.client.send_message.completed",
        "event_outcome": "success",
        "service": "decisao-agent",
        "environment": "test",
        "version": "1.2.3",
        "operation": "send_message",
        "correlation_id": "corr-1",
        "duration_ms": 12.5,
        "http_method": "POST",
        "http_status_code": 202,
    }
    encoded = json.dumps(envelope.payload)
    assert "authorization" not in encoded
    assert "prompt" not in encoded


def test_delivery_retries_identical_event_and_resolves_credential_once() -> None:
    calls: list[tuple[str, bytes, dict[str, str], float]] = []
    statuses = iter([503, 202])
    credential_calls = 0

    def credential() -> str:
        nonlocal credential_calls
        credential_calls += 1
        return "machine-secret"

    def transport(
        endpoint: str,
        body: bytes,
        headers: Mapping[str, str],
        timeout: float,
    ) -> int:
        calls.append((endpoint, body, dict(headers), timeout))
        return next(statuses)

    sink = GovernanceRuntimeTelemetrySink(
        settings(),
        credential,
        transport=transport,
        clock=lambda: datetime(2026, 8, 8, 22, 30, tzinfo=UTC),
        id_factory=lambda: "22222222-2222-4222-8222-222222222222",
    )

    receipt = asyncio.run(sink.emit(event(operation="send_message")))

    assert receipt.event_id == "22222222-2222-4222-8222-222222222222"
    assert receipt.attempts == 2
    assert receipt.status_code == 202
    assert credential_calls == 1
    assert len(calls) == 2
    assert calls[0][1] == calls[1][1]
    assert calls[0][2]["X-Telemetry-Api-Key"] == "machine-secret"
    assert calls[0][0].endswith(
        "/api/v1/agents/11111111-1111-4111-8111-111111111111/runtime-telemetry"
    )


def test_non_retryable_rejection_does_not_retry_or_expose_secret() -> None:
    calls = 0

    def transport(
        _endpoint: str,
        _body: bytes,
        _headers: Mapping[str, str],
        _timeout: float,
    ) -> int:
        nonlocal calls
        calls += 1
        return 403

    sink = GovernanceRuntimeTelemetrySink(
        settings(),
        lambda: "super-sensitive-value",
        transport=transport,
    )

    async def scenario() -> None:
        with pytest.raises(GovernanceRuntimeTelemetryDeliveryError) as exc_info:
            await sink.emit(event())

        assert exc_info.value.status_code == 403
        assert "super-sensitive-value" not in str(exc_info.value)

    asyncio.run(scenario())
    assert calls == 1


def test_transport_failure_exhausts_bounded_retries() -> None:
    calls = 0

    def transport(
        _endpoint: str,
        _body: bytes,
        _headers: Mapping[str, str],
        _timeout: float,
    ) -> int:
        nonlocal calls
        calls += 1
        raise TimeoutError

    sink = GovernanceRuntimeTelemetrySink(
        settings(),
        lambda: "secret",
        transport=transport,
    )

    async def scenario() -> None:
        with pytest.raises(
            GovernanceRuntimeTelemetryDeliveryError,
            match="exhausted retries",
        ):
            await sink.emit(event())

    asyncio.run(scenario())
    assert calls == 3


def test_prepare_rejects_event_name_not_accepted_by_governance() -> None:
    sink = GovernanceRuntimeTelemetrySink(settings(), lambda: "secret")

    with pytest.raises(GovernanceRuntimeTelemetryContractError, match="event_name"):
        sink.prepare(
            StructuredEvent(
                event_name="contains spaces",
                event_outcome=StructuredEventOutcome.SUCCESS,
            )
        )


@pytest.mark.parametrize(
    ("base_url", "message"),
    [
        ("http://governance.example.com", "requires HTTPS"),
        ("https://user:pass@governance.example.com", "without credentials"),
        ("https://governance.example.com?token=value", "without credentials/query"),
    ],
)
def test_settings_reject_unsafe_remote_urls(base_url: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        GovernanceRuntimeTelemetrySettings(
            base_url=base_url,
            agent_id="11111111-1111-4111-8111-111111111111",
            service="svc",
            environment="test",
            version="1",
        )


def test_credential_provider_failure_is_sanitized() -> None:
    def credential() -> str:
        raise RuntimeError("leaked-secret-value")

    sink = GovernanceRuntimeTelemetrySink(settings(), credential)

    async def scenario() -> None:
        with pytest.raises(GovernanceRuntimeTelemetryDeliveryError) as exc_info:
            await sink.emit(event())
        assert "leaked-secret-value" not in str(exc_info.value)
        assert exc_info.value.__cause__ is None

    asyncio.run(scenario())
