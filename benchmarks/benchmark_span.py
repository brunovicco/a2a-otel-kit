#!/usr/bin/env python3
"""Measure local span, propagation, sanitization, and opt-in loopback OTLP overhead."""

import argparse
import math
import os
import statistics
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import urlparse

from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.trace import Tracer

from a2a_otel_kit.adapters.propagation import inject_trace_context
from a2a_otel_kit.adapters.tracing import build_tracer_provider
from a2a_otel_kit.application.ports import TracerLifecycle
from a2a_otel_kit.application.settings import ObservabilitySettings
from a2a_otel_kit.domain.attributes import sanitize_attributes

_SPAN_NAME = "benchmark.operation"
_MAX_LOCAL_OTLP_ITERATIONS = 1_000
_LOCAL_OTLP_ENVIRONMENT = {
    "NO_PROXY": "127.0.0.1,::1",
    "no_proxy": "127.0.0.1,::1",
    "OTEL_BSP_MAX_QUEUE_SIZE": "2048",
    "OTEL_BSP_MAX_EXPORT_BATCH_SIZE": "512",
}
_REJECTED_VALUE = "synthetic"
_ATTRIBUTES: dict[str, object] = {
    "service": "benchmark",
    "environment": "local",
    "operation": "measure_span",
    "outcome": "success",
    "not_allowlisted": "dropped",
    "authorization_token": _REJECTED_VALUE,
}


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    """Robust per-operation timings for one benchmark case."""

    name: str
    samples_microseconds: tuple[float, ...]

    @property
    def minimum(self) -> float:
        """Return the fastest sample in microseconds per operation."""
        return min(self.samples_microseconds)

    @property
    def median(self) -> float:
        """Return the median in microseconds per operation."""
        return statistics.median(self.samples_microseconds)

    @property
    def p95(self) -> float:
        """Return the nearest-rank 95th percentile in microseconds per operation."""
        ordered = sorted(self.samples_microseconds)
        return ordered[math.ceil(len(ordered) * 0.95) - 1]


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    """Validated command-line configuration for a benchmark run."""

    iterations: int
    samples: int
    warmups: int
    otlp_endpoint: str | None
    otlp_iterations: int
    otlp_timeout_seconds: float


def _positive_int(value: str) -> int:
    """Parse a strictly positive integer for argparse."""
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _non_negative_int(value: str) -> int:
    """Parse a non-negative integer for argparse."""
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return parsed


def _positive_float(value: str) -> float:
    """Parse a finite, strictly positive float for argparse."""
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a finite number greater than zero")
    return parsed


def _bounded_otlp_iterations(value: str) -> int:
    """Keep each exported batch below the provider's default span queue capacity."""
    parsed = _positive_int(value)
    if parsed > _MAX_LOCAL_OTLP_ITERATIONS:
        raise argparse.ArgumentTypeError(
            f"value must be at most {_MAX_LOCAL_OTLP_ITERATIONS} to avoid queue drops"
        )
    return parsed


@contextmanager
def _controlled_local_otlp_environment() -> Iterator[None]:
    """Disable ambient proxies and pin batch capacity for the isolated local measurement."""
    previous = {key: os.environ.get(key) for key in _LOCAL_OTLP_ENVIRONMENT}
    os.environ.update(_LOCAL_OTLP_ENVIRONMENT)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _local_otlp_endpoint(value: str) -> str:
    """Accept an explicit OTLP URL only when it targets a loopback IP literal."""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise argparse.ArgumentTypeError("OTLP endpoint must use http:// or https://")
    if parsed.hostname not in {"127.0.0.1", "::1"}:
        raise argparse.ArgumentTypeError("OTLP benchmark endpoint must use a loopback IP literal")
    if parsed.username is not None or parsed.password is not None:
        raise argparse.ArgumentTypeError("OTLP endpoint must not contain credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise argparse.ArgumentTypeError("OTLP endpoint contains an invalid port") from exc
    if port is None:
        raise argparse.ArgumentTypeError("OTLP endpoint must include an explicit port")
    return value


def parse_args() -> BenchmarkConfig:
    """Parse and validate benchmark arguments without enabling network by default."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=_positive_int, default=10_000)
    parser.add_argument("--samples", type=_positive_int, default=15)
    parser.add_argument("--warmups", type=_non_negative_int, default=3)
    parser.add_argument(
        "--otlp-endpoint",
        type=_local_otlp_endpoint,
        help="Explicit loopback OTLP/HTTP traces URL; omitted means no network benchmark",
    )
    parser.add_argument(
        "--otlp-iterations",
        type=_bounded_otlp_iterations,
        default=_MAX_LOCAL_OTLP_ITERATIONS,
        help="Spans per exported sample (bounded below the default batch queue capacity)",
    )
    parser.add_argument("--otlp-timeout-seconds", type=_positive_float, default=2.0)
    namespace = parser.parse_args()
    return BenchmarkConfig(
        iterations=namespace.iterations,
        samples=namespace.samples,
        warmups=namespace.warmups,
        otlp_endpoint=namespace.otlp_endpoint,
        otlp_iterations=namespace.otlp_iterations,
        otlp_timeout_seconds=namespace.otlp_timeout_seconds,
    )


def measure(
    name: str,
    operation: Callable[[], None],
    *,
    iterations: int,
    sample_count: int,
    warmup_count: int,
    after_batch: Callable[[], None] | None = None,
) -> BenchmarkResult:
    """Measure repeated operations and return independent per-operation timing samples."""
    samples: list[float] = []
    for sample_index in range(warmup_count + sample_count):
        started = time.perf_counter_ns()
        for _ in range(iterations):
            operation()
        if after_batch is not None:
            after_batch()
        elapsed = time.perf_counter_ns() - started
        if sample_index >= warmup_count:
            samples.append(elapsed / iterations / 1_000)
    return BenchmarkResult(name=name, samples_microseconds=tuple(samples))


def _baseline() -> None:
    """Perform the intentionally minimal baseline operation."""


def _span_operation(tracer: Tracer) -> Callable[[], None]:
    """Build an operation that creates and ends one recording span."""

    def operation() -> None:
        with tracer.start_as_current_span(_SPAN_NAME):
            pass

    return operation


def _span_with_propagation_operation(tracer: Tracer) -> Callable[[], None]:
    """Build an operation that creates a span and injects its W3C context."""

    def operation() -> None:
        carrier: dict[str, str] = {}
        with tracer.start_as_current_span(_SPAN_NAME):
            inject_trace_context(carrier)

    return operation


def _span_with_sanitizer_operation(tracer: Tracer) -> Callable[[], None]:
    """Build an operation that sanitizes input and creates an attributed span."""

    def operation() -> None:
        attributes = {
            key: value
            for key, value in sanitize_attributes(_ATTRIBUTES).items()
            if value is not None
        }
        with tracer.start_as_current_span(_SPAN_NAME, attributes=attributes):
            pass

    return operation


def _flush_with_timeout(lifecycle: TracerLifecycle, timeout_seconds: float) -> None:
    """Wait for batch processing, raising only when the SDK reports a flush timeout."""
    if not lifecycle.force_flush(timeout_millis=int(timeout_seconds * 1_000)):
        raise RuntimeError("local OTLP processor did not flush within the configured timeout")


def _measure_local_otlp(config: BenchmarkConfig) -> BenchmarkResult | None:
    """Measure span creation plus amortized flush to an explicitly requested loopback endpoint."""
    if config.otlp_endpoint is None:
        return None
    with _controlled_local_otlp_environment():
        settings = ObservabilitySettings(
            service_name="a2a-otel-kit-benchmark",
            service_version="local",
            environment="benchmark",
            enabled=True,
            otlp_endpoint=config.otlp_endpoint,
            otlp_timeout_seconds=config.otlp_timeout_seconds,
        )
        provider, lifecycle = build_tracer_provider(settings)
        if lifecycle is None:
            raise RuntimeError("enabled local OTLP benchmark did not create an exporter lifecycle")
        tracer = provider.get_tracer("a2a-otel-kit-benchmark", "local")
        try:
            return measure(
                "span + local OTLP",
                _span_operation(tracer),
                iterations=config.otlp_iterations,
                sample_count=config.samples,
                warmup_count=config.warmups,
                after_batch=lambda: _flush_with_timeout(lifecycle, config.otlp_timeout_seconds),
            )
        finally:
            lifecycle.shutdown()


def _print_results(results: list[BenchmarkResult], config: BenchmarkConfig) -> None:
    """Print stable Markdown output suitable for copying into results documentation."""
    print(f"iterations/sample: {config.iterations}; samples: {config.samples}")
    print("\n| Case | Minimum (µs/op) | Median (µs/op) | p95 (µs/op) |")
    print("| --- | ---: | ---: | ---: |")
    for result in results:
        print(f"| {result.name} | {result.minimum:.3f} | {result.median:.3f} | {result.p95:.3f} |")
    if config.otlp_endpoint is None:
        print("\nLocal OTLP: not measured (pass --otlp-endpoint with a loopback traces URL).")
    else:
        print(f"\nLocal OTLP iterations/sample: {config.otlp_iterations}")


def main() -> int:
    """Run the local benchmark cases and the optional loopback OTLP case."""
    config = parse_args()
    provider = SDKTracerProvider()
    tracer = provider.get_tracer("a2a-otel-kit-benchmark", "local")
    try:
        results = [
            measure(
                "baseline",
                _baseline,
                iterations=config.iterations,
                sample_count=config.samples,
                warmup_count=config.warmups,
            ),
            measure(
                "span only",
                _span_operation(tracer),
                iterations=config.iterations,
                sample_count=config.samples,
                warmup_count=config.warmups,
            ),
            measure(
                "span + propagation",
                _span_with_propagation_operation(tracer),
                iterations=config.iterations,
                sample_count=config.samples,
                warmup_count=config.warmups,
            ),
            measure(
                "span + sanitizer",
                _span_with_sanitizer_operation(tracer),
                iterations=config.iterations,
                sample_count=config.samples,
                warmup_count=config.warmups,
            ),
        ]
    finally:
        provider.shutdown()

    local_otlp = _measure_local_otlp(config)
    if local_otlp is not None:
        results.append(local_otlp)
    _print_results(results, config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
