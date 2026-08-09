import argparse
import os

import pytest
from benchmarks.benchmark_span import (
    _bounded_otlp_iterations,
    _controlled_local_otlp_environment,
    _local_otlp_endpoint,
)


@pytest.mark.parametrize(
    "endpoint",
    ["http://127.0.0.1:4318/v1/traces", "http://[::1]:4318/v1/traces"],
)
def test_local_otlp_endpoint_accepts_only_explicit_loopback_addresses(endpoint: str) -> None:
    assert _local_otlp_endpoint(endpoint) == endpoint


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://localhost:4318/v1/traces",
        "http://collector.example:4318/v1/traces",
        "http://user:password@127.0.0.1:4318/v1/traces",
        "http://127.0.0.1/v1/traces",
    ],
)
def test_local_otlp_endpoint_rejects_non_literal_remote_or_credentialed_urls(
    endpoint: str,
) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        _local_otlp_endpoint(endpoint)


def test_local_otlp_iterations_stay_below_the_configured_queue() -> None:
    assert _bounded_otlp_iterations("1000") == 1000
    with pytest.raises(argparse.ArgumentTypeError):
        _bounded_otlp_iterations("1001")


def test_local_otlp_environment_disables_proxies_and_restores_process_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NO_PROXY", "original.example")
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setenv("OTEL_BSP_MAX_QUEUE_SIZE", "8")
    monkeypatch.delenv("OTEL_BSP_MAX_EXPORT_BATCH_SIZE", raising=False)

    with _controlled_local_otlp_environment():
        assert os.environ["NO_PROXY"] == "127.0.0.1,::1"
        assert os.environ["no_proxy"] == "127.0.0.1,::1"
        assert os.environ["OTEL_BSP_MAX_QUEUE_SIZE"] == "2048"
        assert os.environ["OTEL_BSP_MAX_EXPORT_BATCH_SIZE"] == "512"

    assert os.environ["NO_PROXY"] == "original.example"
    assert "no_proxy" not in os.environ
    assert os.environ["OTEL_BSP_MAX_QUEUE_SIZE"] == "8"
    assert "OTEL_BSP_MAX_EXPORT_BATCH_SIZE" not in os.environ
