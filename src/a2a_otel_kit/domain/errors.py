"""Domain-level observability errors.

Pure Python, no framework or SDK dependency: these errors are raised by domain and application
code and translated at adapter/entrypoint boundaries when they cross into infrastructure code.
"""


class ObservabilityError(Exception):
    """Base class for all errors raised by this library."""


class InvalidObservabilityConfigurationError(ObservabilityError):
    """Raised when observability settings fail validation before providers are installed."""


class InvalidStructuredEventError(ObservabilityError):
    """Raised when a structured event does not satisfy the versioned event schema."""
