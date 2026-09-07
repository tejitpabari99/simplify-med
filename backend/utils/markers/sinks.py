"""
Sink interface and two reference implementations.

A sink receives the event dict produced by `CodeMarker._emit`:

    {
      "name": "orders.create",
      "duration_ms": 12,
      "success": True,
      "dimensions": {...},
    }

Implement your own to ship to Kusto, OpenTelemetry, statsd, an HTTP endpoint,
a log file — anything.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Protocol


class Sink(Protocol):
    def emit(self, event: Dict[str, Any]) -> None: ...


class ConsoleSink:
    """Prints one JSON line per event. Handy for development."""

    def __init__(self, stream=None) -> None:
        self._stream = stream or sys.stdout

    def emit(self, event: Dict[str, Any]) -> None:
        line = {"timestamp": datetime.now(timezone.utc).isoformat(), **event}
        print(json.dumps(line, ensure_ascii=False), file=self._stream)


class InMemorySink:
    """Captures events in a list. Useful in tests."""

    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    def emit(self, event: Dict[str, Any]) -> None:
        self.events.append(event)


import logging
from typing import Any, Dict  # noqa: F811


_metric_logger = logging.getLogger("simplify.metrics")
_event_logger = logging.getLogger("simplify.markers")


class SimplifySink:
    """Marker sink: one event → a log-based-metric line + a timeline log line."""

    def emit(self, event: Dict[str, Any]) -> None:
        name = event["name"]
        duration_ms = event["duration_ms"]
        success = event["success"]
        dims = event.get("dimensions") or {}

        # (1) metric line — Metrics Explorer log-based metrics read these
        _metric_logger.info(
            "simplify_metric",
            extra={
                "metric": True,
                "metric_type": "marker",
                "operation": name,
                "duration_ms": round(duration_ms, 1),
                "success": success,
                "outcome": dims.get("OpOutcome", "Succeeded" if success else "Failed"),
                **dims,
            },
        )

        # (2) timeline line — Logs Explorer session view reads these
        level = logging.INFO if success else logging.ERROR
        _event_logger.log(
            level, "op_complete",
            extra={"operation": name, "duration_ms": round(duration_ms, 1),
                   "success": success, **dims},
        )
