"""Shared fixtures for logging-sensitive tests."""

import logging
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _reset_stdlib_logging() -> Iterator[None]:
    """Reset stdlib logging handlers and level around each test.

    ``configure_logging()`` mutates the root logger as a process-wide side effect; resetting
    around every test keeps tests independent of execution order.
    """
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    yield
    root.handlers = original_handlers
    root.level = original_level
