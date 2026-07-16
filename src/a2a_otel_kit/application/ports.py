"""Application-owned ports, defined near the use case that consumes them.

Adapters satisfy these Protocols structurally; no inheritance is required. The OpenTelemetry SDK's
own ``TracerProvider`` already implements :class:`TracerLifecycle` without any wrapper code.
"""

from typing import Protocol


class TracerLifecycle(Protocol):
    """Flush and shutdown behavior for an installed tracer backend.

    Absent (``None``) when observability is disabled, since there is nothing to flush or shut
    down for a no-op tracer provider.
    """

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Block until pending spans are exported or ``timeout_millis`` elapses."""
        ...

    def shutdown(self) -> None:
        """Release exporter resources. Safe to call at most once per backend instance."""
        ...
