# Minimal adoption

Install only the integrations the process uses:

```bash
uv add "a2a-otel-kit[a2a,mcp]"
```

Create one explicit observability instance and always release it:

```python
import os

from a2a_otel_kit import Observability, ObservabilitySettings


def otlp_headers() -> dict[str, str]:
    # The application owns secret lookup. Never print or log this mapping.
    return {"authorization": os.environ["OTLP_AUTHORIZATION"]}


settings = ObservabilitySettings(
    service_name="example-agent",
    service_version="0.4.2",
    environment="local",
    enabled=True,
    otlp_endpoint="http://127.0.0.1:4318/v1/traces",
)
observability = Observability.configure(settings, otlp_headers_provider=otlp_headers)
try:
    # Pass `observability` to the helpers in a2a_adoption.py or mcp_adoption.py.
    ...
finally:
    observability.shutdown()
```

For a local Collector without authentication, omit `otlp_headers_provider`. A2A wrapping uses
`TracingClient` and `TracingRequestHandler`; MCP Streamable HTTP wrapping uses
`TracingAsyncTransport` and `TracingASGIMiddleware`. The example modules expose small typed helper
functions for those exact public SDK boundaries and perform no work or network I/O when imported.
