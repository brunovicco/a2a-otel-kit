import os
from pathlib import Path

import pytest

from a2a_otel_kit.application.settings import ObservabilitySettings
from a2a_otel_kit.entrypoints.observability import Observability

_ENDPOINT_ENV = "A2A_OTEL_KIT_COLLECTOR_ENDPOINT"
_RECEIPT_ENV = "A2A_OTEL_KIT_COLLECTOR_RECEIPT_FILE"


@pytest.mark.integration
def test_collector_receives_exported_span() -> None:
    """Opt-in: require positive span evidence from the Collector file exporter."""
    endpoint = os.environ.get(_ENDPOINT_ENV)
    receipt_value = os.environ.get(_RECEIPT_ENV)
    if endpoint is None or receipt_value is None:
        pytest.skip(f"set {_ENDPOINT_ENV} and {_RECEIPT_ENV} to run the Collector integration")

    receipt = Path(receipt_value).resolve()
    if not receipt.is_file():
        pytest.fail(f"Collector receipt file does not exist: {receipt}")
    initial_size = receipt.stat().st_size
    observability = Observability.configure(
        ObservabilitySettings(
            service_name="a2a-otel-kit-collector-integration",
            service_version="0.3.1",
            environment="integration",
            enabled=True,
            otlp_endpoint=endpoint,
            otlp_timeout_seconds=5,
        )
    )
    with observability.start_span(
        "collector.integration.receipt", attributes={"operation": "collector.integration.receipt"}
    ):
        pass
    try:
        assert observability.flush(5), "OTLP exporter did not flush within five seconds"
    finally:
        observability.shutdown(5)

    with receipt.open("rb") as handle:
        handle.seek(initial_size)
        appended = handle.read().decode("utf-8", errors="replace")

    assert "collector.integration.receipt" in appended
    assert "a2a-otel-kit-collector-integration" in appended
