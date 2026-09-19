"""Explicit offline execution for single-process CLI workflows."""
from contextlib import contextmanager
from sentinel.config import default_config


@contextmanager
def offline_mode():
    """Temporarily disable model stages; use outside concurrent review invocations."""
    previous = default_config.provider
    default_config.provider = "heuristics"
    try:
        yield
    finally:
        default_config.provider = previous
