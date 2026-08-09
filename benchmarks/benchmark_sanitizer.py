#!/usr/bin/env python3
"""Measure attribute sanitization across representative safe and rejected inputs."""

import argparse
import math
import statistics
import time
from collections.abc import Mapping
from dataclasses import dataclass

from a2a_otel_kit.domain.attributes import sanitize_attributes

_REJECTED_VALUE = "synthetic"
_SAFE_ATTRIBUTES: dict[str, object] = {
    "service": "risk-agent",
    "environment": "benchmark",
    "version": "1.0.0",
    "component": "a2a",
    "operation": "get_task",
    "outcome": "success",
    "duration_ms": 12.5,
    "retry_count": 0,
}
_MIXED_ATTRIBUTES: dict[str, object] = {
    **_SAFE_ATTRIBUTES,
    "prompt": "not allowlisted",
    "authorization_token": _REJECTED_VALUE,
    "payload": {"customer": "not scalar"},
    "request_id": "x" * 257,
}
_REJECTED_ATTRIBUTES: dict[str, object] = {
    "prompt": "not allowlisted",
    "business_payload": ["not", "scalar"],
    "api_key": _REJECTED_VALUE,
    "request_id": "x" * 257,
}


@dataclass(frozen=True, slots=True)
class SanitizerResult:
    """Per-call timings for one sanitizer input shape."""

    name: str
    samples_microseconds: tuple[float, ...]

    @property
    def minimum(self) -> float:
        """Return the fastest sample in microseconds per call."""
        return min(self.samples_microseconds)

    @property
    def median(self) -> float:
        """Return the median in microseconds per call."""
        return statistics.median(self.samples_microseconds)

    @property
    def p95(self) -> float:
        """Return the nearest-rank 95th percentile in microseconds per call."""
        ordered = sorted(self.samples_microseconds)
        return ordered[math.ceil(len(ordered) * 0.95) - 1]


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


def measure_sanitizer(
    name: str,
    attributes: Mapping[str, object],
    *,
    iterations: int,
    sample_count: int,
    warmup_count: int,
) -> SanitizerResult:
    """Measure one sanitizer input using independent per-call timing samples."""
    samples: list[float] = []
    for sample_index in range(warmup_count + sample_count):
        started = time.perf_counter_ns()
        for _ in range(iterations):
            sanitize_attributes(attributes)
        elapsed = time.perf_counter_ns() - started
        if sample_index >= warmup_count:
            samples.append(elapsed / iterations / 1_000)
    return SanitizerResult(name=name, samples_microseconds=tuple(samples))


def main() -> int:
    """Run sanitizer cases and print robust Markdown summary statistics."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=_positive_int, default=50_000)
    parser.add_argument("--samples", type=_positive_int, default=15)
    parser.add_argument("--warmups", type=_non_negative_int, default=3)
    args = parser.parse_args()

    results = [
        measure_sanitizer(
            "8 allowlisted values",
            _SAFE_ATTRIBUTES,
            iterations=args.iterations,
            sample_count=args.samples,
            warmup_count=args.warmups,
        ),
        measure_sanitizer(
            "8 allowed + 4 rejected",
            _MIXED_ATTRIBUTES,
            iterations=args.iterations,
            sample_count=args.samples,
            warmup_count=args.warmups,
        ),
        measure_sanitizer(
            "4 rejected values",
            _REJECTED_ATTRIBUTES,
            iterations=args.iterations,
            sample_count=args.samples,
            warmup_count=args.warmups,
        ),
    ]

    print(f"iterations/sample: {args.iterations}; samples: {args.samples}")
    print("\n| Input | Minimum (µs/call) | Median (µs/call) | p95 (µs/call) |")
    print("| --- | ---: | ---: | ---: |")
    for result in results:
        print(f"| {result.name} | {result.minimum:.3f} | {result.median:.3f} | {result.p95:.3f} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
