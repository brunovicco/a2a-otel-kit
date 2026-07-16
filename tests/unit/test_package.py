"""Package-level smoke tests: importability, public API surface, and import-time I/O safety."""

import importlib.util
import socket

import pytest


def test_package_is_importable() -> None:
    """The generated package is importable."""
    import a2a_otel_kit  # noqa: F401


def test_public_api_exports_the_documented_surface() -> None:
    """The documented public API is importable from the package root, not a submodule."""
    from a2a_otel_kit import (
        Observability,
        ObservabilityError,
        ObservabilitySettings,
        StructuredEvent,
        StructuredEventOutcome,
        continue_trace,
        extract_trace_context,
        inject_trace_context,
        sanitize_attributes,
    )

    assert issubclass(ObservabilityError, Exception)
    assert callable(Observability.configure)
    assert callable(ObservabilitySettings)
    assert callable(StructuredEvent)
    assert callable(StructuredEventOutcome)
    assert callable(continue_trace)
    assert callable(extract_trace_context)
    assert callable(inject_trace_context)
    assert callable(sanitize_attributes)


def test_import_performs_no_network_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Importing the package must never open a socket; initialization is always explicit."""

    def _blocked(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("network I/O attempted during import")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)

    spec = importlib.util.find_spec("a2a_otel_kit")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # must not raise
