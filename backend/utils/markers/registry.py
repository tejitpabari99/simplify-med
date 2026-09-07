"""Process-wide sink registration. Single global slot — keep it simple."""

from __future__ import annotations

from typing import Optional

from .sinks import Sink

_sink: Optional[Sink] = None


def register_sink(sink: Optional[Sink]) -> None:
    """Register the active sink. Pass `None` to disable emission."""
    global _sink
    _sink = sink


def resolve_sink() -> Optional[Sink]:
    return _sink
