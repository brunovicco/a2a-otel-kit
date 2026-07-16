"""Optional Streamable HTTP tracing for the official MCP Python SDK.

Requires the ``mcp`` extra.  The adapter uses only public boundaries: an HTTPX
``AsyncBaseTransport`` passed to ``streamable_http_client(http_client=...)`` and a generic ASGI
middleware wrapped around ``FastMCP.streamable_http_app()``.  Request and response bodies are
never read or inspected.
"""

from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version
from typing import Protocol

from opentelemetry.trace import SpanKind, StatusCode

try:
    version("mcp")
    import httpx
except (ImportError, PackageNotFoundError) as exc:
    raise ImportError(
        "a2a_otel_kit.adapters.mcp requires the optional 'mcp' extra: install with "
        "`pip install a2a-otel-kit[mcp]` (or `uv add a2a-otel-kit[mcp]`)."
    ) from exc

from a2a_otel_kit.adapters.propagation import continue_trace, inject_trace_context
from a2a_otel_kit.application.ports import ObservabilityFacade
from a2a_otel_kit.domain.attributes import StructuredEventOutcome

type ASGIMessage = dict[str, object]
type Scope = Mapping[str, object]


class Receive(Protocol):
    """Minimal ASGI receive callable contract."""

    async def __call__(self) -> ASGIMessage:
        """Receive the next ASGI message."""
        ...


class Send(Protocol):
    """Minimal ASGI send callable contract."""

    async def __call__(self, message: ASGIMessage) -> None:
        """Send one ASGI message."""
        ...


class ASGIApp(Protocol):
    """Minimal ASGI application contract returned by FastMCP."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle one ASGI scope."""
        ...


_CLIENT_OPERATION = "mcp.client.streamable_http"
_SERVER_OPERATION = "mcp.server.streamable_http"


def _safe_headers(scope: Scope) -> Mapping[str, str]:
    """Extract only W3C propagation fields from untrusted ASGI headers."""
    carrier: dict[str, str] = {}
    headers = scope.get("headers")
    if not isinstance(headers, list):
        return carrier
    for item in headers:
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        raw_name, raw_value = item
        if not isinstance(raw_name, bytes) or not isinstance(raw_value, bytes):
            continue
        try:
            name = raw_name.decode("ascii").lower()
            if name in {"traceparent", "tracestate"}:
                carrier[name] = raw_value.decode("ascii")
        except UnicodeDecodeError:
            continue
    return carrier


class TracingAsyncTransport(httpx.AsyncBaseTransport):
    """Add W3C propagation and one CLIENT span to an HTTPX async transport."""

    def __init__(self, inner: httpx.AsyncBaseTransport, observability: ObservabilityFacade) -> None:
        """Wrap an existing transport without taking ownership of request bodies."""
        self._inner = inner
        self._observability = observability

    @classmethod
    def wrap(
        cls, inner: httpx.AsyncBaseTransport, observability: ObservabilityFacade
    ) -> httpx.AsyncBaseTransport:
        """Wrap a transport once, avoiding duplicate instrumentation."""
        if isinstance(inner, cls):
            return inner
        return cls(inner, observability)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Inject trace headers and delegate without reading either HTTP body."""
        with self._observability.start_span(
            _CLIENT_OPERATION,
            kind=SpanKind.CLIENT,
            attributes={"operation": _CLIENT_OPERATION},
            record_exception=False,
        ) as span:
            self._observability.emit_event(
                _CLIENT_OPERATION + ".started",
                StructuredEventOutcome.STARTED,
                operation=_CLIENT_OPERATION,
            )
            carrier: dict[str, str] = {}
            inject_trace_context(carrier)
            # HTTPX headers are case-insensitive. Remove both W3C fields first so a caller's stale
            # traceparent cannot be paired with an unrelated tracestate (or vice versa).
            request.headers.pop("traceparent", None)
            request.headers.pop("tracestate", None)
            for name, value in carrier.items():
                request.headers[name] = value
            try:
                response = await self._inner.handle_async_request(request)
            except BaseException:
                span.set_status(StatusCode.ERROR)
                self._observability.emit_event(
                    _CLIENT_OPERATION + ".failed",
                    StructuredEventOutcome.ERROR,
                    operation=_CLIENT_OPERATION,
                )
                raise
            if response.status_code >= 400:
                span.set_status(StatusCode.ERROR)
                self._observability.emit_event(
                    _CLIENT_OPERATION + ".failed",
                    StructuredEventOutcome.ERROR,
                    operation=_CLIENT_OPERATION,
                )
            else:
                self._observability.emit_event(
                    _CLIENT_OPERATION + ".completed",
                    StructuredEventOutcome.SUCCESS,
                    operation=_CLIENT_OPERATION,
                )
            return response

    async def aclose(self) -> None:
        """Close the wrapped transport deterministically."""
        await self._inner.aclose()


class TracingASGIMiddleware:
    """Continue W3C context and trace one inbound Streamable HTTP ASGI request."""

    def __init__(self, app: ASGIApp, observability: ObservabilityFacade) -> None:
        """Wrap an ASGI app returned by ``FastMCP.streamable_http_app()``."""
        self._app = app
        self._observability = observability

    @classmethod
    def wrap(cls, app: ASGIApp, observability: ObservabilityFacade) -> ASGIApp:
        """Wrap an app once, avoiding duplicate instrumentation."""
        if isinstance(app, cls):
            return app
        return cls(app, observability)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Trace HTTP scopes while passing all protocol data through untouched."""
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        with (
            continue_trace(_safe_headers(scope)),
            self._observability.start_span(
                _SERVER_OPERATION,
                kind=SpanKind.SERVER,
                attributes={"operation": _SERVER_OPERATION},
                record_exception=False,
            ) as span,
        ):
            self._observability.emit_event(
                _SERVER_OPERATION + ".started",
                StructuredEventOutcome.STARTED,
                operation=_SERVER_OPERATION,
            )
            response_status: int | None = None

            async def observe_status(message: ASGIMessage) -> None:
                nonlocal response_status
                if message.get("type") == "http.response.start":
                    status = message.get("status")
                    if isinstance(status, int) and not isinstance(status, bool):
                        response_status = status
                await send(message)

            try:
                await self._app(scope, receive, observe_status)
            except BaseException:
                span.set_status(StatusCode.ERROR)
                self._observability.emit_event(
                    _SERVER_OPERATION + ".failed",
                    StructuredEventOutcome.ERROR,
                    operation=_SERVER_OPERATION,
                )
                raise
            if response_status is not None and response_status >= 400:
                span.set_status(StatusCode.ERROR)
                self._observability.emit_event(
                    _SERVER_OPERATION + ".failed",
                    StructuredEventOutcome.ERROR,
                    operation=_SERVER_OPERATION,
                )
            else:
                self._observability.emit_event(
                    _SERVER_OPERATION + ".completed",
                    StructuredEventOutcome.SUCCESS,
                    operation=_SERVER_OPERATION,
                )
