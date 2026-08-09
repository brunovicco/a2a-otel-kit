# Overhead benchmarks

These microbenchmarks make the local cost of the library's core telemetry operations visible. They
are diagnostic evidence, not a performance guarantee or a release gate. Run a workload benchmark
in the consuming application before making a capacity decision.

No additional dependency is required: the scripts use the Python standard library, the installed
OpenTelemetry packages, and current `a2a-otel-kit` APIs.

## Run the default, network-free suite

From the repository root:

```bash
uv run python benchmarks/benchmark_span.py
uv run python benchmarks/benchmark_sanitizer.py
```

`benchmark_span.py` reports:

- `baseline`: Python call/loop timing floor;
- `span only`: recording SDK span creation/end with no processor or exporter;
- `span + propagation`: the span plus W3C carrier injection;
- `span + sanitizer`: sanitization of representative allowed/rejected attributes plus the span;
- `span + local OTLP`: present only when explicitly enabled.

`benchmark_sanitizer.py` isolates the sanitizer across accepted, mixed, and fully rejected input
shapes. Both scripts perform warmups and report the minimum, median, and nearest-rank p95 across
independent samples. Prefer the median for comparison; retain p95 to expose scheduler or runtime
noise rather than publishing only the fastest result.

Tune sample sizes explicitly when needed:

```bash
uv run python benchmarks/benchmark_span.py --iterations 20000 --samples 20 --warmups 5
uv run python benchmarks/benchmark_sanitizer.py --iterations 100000 --samples 20 --warmups 5
```

## Explicit local OTLP measurement

Network export is disabled unless `--otlp-endpoint` is passed. The option accepts only an explicit
loopback IP literal with a port and rejects credentials. During the local measurement, the script
also disables ambient HTTP proxies and restores the original process environment afterward, which
prevents the benchmark from sending data to a remote Collector accidentally.

Start a local OTLP/HTTP Collector separately, then run for example:

```bash
uv run python benchmarks/benchmark_span.py \
  --otlp-endpoint http://127.0.0.1:4318/v1/traces
```

The OTLP case includes span creation and an amortized `force_flush()` once per sample, so it waits
for the batch processor rather than measuring queue insertion alone. It uses the configured bounded
timeout and fails when the SDK reports that batch processing did not flush in time. A successful
flush is not proof that a Collector accepted or stored the spans; exporter errors remain visible in
the command output, and Collector startup, shutdown, resource monitoring, and positive receipt
validation remain the operator's responsibility.

The local-export case uses `1,000` spans per sample by default, independently of the network-free
`--iterations` value. The benchmark explicitly sets the batch queue to `2,048` spans and the export
batch to `512`, then caps `--otlp-iterations` at `1,000`; a measured sample therefore stays below
the queue capacity instead of silently benchmarking dropped spans.

`force_flush()` uses the CLI's bounded timeout. Lifecycle shutdown happens only after that flush
and uses the OpenTelemetry SDK's own bounded shutdown (up to 30 seconds in the tested SDK), so an
unresponsive exporter can make process exit take longer than `--otlp-timeout-seconds`.

## Interpreting results

- Results depend on CPU, power management, OS scheduling, Python/OpenTelemetry versions, process
  contention, Collector configuration, batching, payload size, and network conditions.
- The baseline is not a business-operation baseline and should not be subtracted as proof of
  end-to-end application overhead.
- `span only` intentionally has no processor/exporter, isolating local recording cost but omitting
  queue/export work.
- The propagation case allocates a fresh carrier on each operation. Real transports add their own
  serialization and I/O costs.
- Sanitizer inputs are representative and bounded; different key counts and string lengths have
  different costs.
- Local OTLP amortizes one flush over each iteration batch. It is not comparable to a production
  batch processor under sustained traffic and does not measure Collector/backend ingestion.
- Microsecond values can vary between runs. Record hardware, software versions, exact command, and
  whether local infrastructure was active whenever publishing new results.

The latest repository-local observation is in [results.md](results.md). Re-run rather than assuming
those values apply to another environment.
