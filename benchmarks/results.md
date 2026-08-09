# Benchmark results

This file records reproducible context and observed results, not performance promises. Values are
filled from actual runs of the scripts in this repository, including a loopback Collector receipt.

## Environment

- Date: 2026-08-09
- Project version: 0.5.0 development tree
- Python: 3.13.2
- Platform: macOS 26.5.2, arm64 (`platform.processor()` reported `arm`)
- Commands:
  - `uv run python benchmarks/benchmark_span.py --otlp-endpoint http://127.0.0.1:4318/v1/traces`
  - `uv run python benchmarks/benchmark_sanitizer.py`
- Local OTLP infrastructure: `compose.collector.yml`, OpenTelemetry Collector Contrib `0.153.0`
  using the repository's digest-pinned image and file-receipt configuration

## Span path

Network-free cases used `10,000` iterations per sample. Local OTLP used `1,000` iterations per
sample to stay below the batch queue capacity. Every case used `3` warmups and `15` measured
samples:

| Case | Minimum (µs/op) | Median (µs/op) | p95 (µs/op) |
| --- | ---: | ---: | ---: |
| baseline | 0.021 | 0.022 | 0.037 |
| span only | 8.266 | 8.966 | 12.493 |
| span + propagation | 9.455 | 10.263 | 16.727 |
| span + sanitizer | 13.796 | 14.385 | 18.556 |
| span + local OTLP | 22.429 | 41.166 | 70.021 |

## Sanitizer

`50,000` iterations per sample, `3` warmups, `15` measured samples:

| Input | Minimum (µs/call) | Median (µs/call) | p95 (µs/call) |
| --- | ---: | ---: | ---: |
| 8 allowlisted values | 5.898 | 6.585 | 8.995 |
| 8 allowed + 4 rejected | 6.690 | 6.924 | 8.284 |
| 4 rejected values | 1.026 | 1.067 | 1.216 |

## Local OTLP

The local OTLP timing includes recording through the library's batch processor and an amortized
`force_flush()` after each sample. The isolated Collector file exporter wrote `3,970,229` bytes
and the receipt contained the synthetic `a2a-otel-kit-benchmark` service name. That is positive
receipt evidence for this run, not a guarantee about production Collector or backend latency.
