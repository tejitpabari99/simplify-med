"""
Core primitives: `Scope`, `CodeMarker`, and the `@code_marker` decorator.

Each *concrete subclass* of `CodeMarker` is a singleton "operation marker" —
the class object itself is the singleton, no instances needed. Tag it with
`@code_marker("name")` and call `Marker.execute(action)` /
`await Marker.execute_async(action)` to wrap work.
"""

from __future__ import annotations

import inspect
import time
from typing import Any, Awaitable, Callable, Dict, TypeVar

from utils.constants import Constants

T = TypeVar("T")


class Scope:
    """Per-execution context handed to the action — collects dimensions."""

    __slots__ = ("name", "_dims", "_start_ns", "_failed")

    def __init__(self, name: str) -> None:
        self.name = name
        self._dims: Dict[str, Any] = {}
        self._start_ns = time.perf_counter_ns()
        self._failed = False

    def add(self, key: str, value: Any) -> None:
        """Attach a custom dimension. Last write wins."""
        if value is not None:
            self._dims[key] = value

    def add_many(self, mapping: Dict[str, Any]) -> None:
        for k, v in mapping.items():
            self.add(k, v)

    def mark_failed(self) -> None:
        """Force the outcome to Failed without raising."""
        self._failed = True

    # internals
    def _finalize(self, raised: bool) -> tuple[int, bool, Dict[str, Any]]:
        duration_ms = (time.perf_counter_ns() - self._start_ns) // 1_000_000
        success = not (raised or self._failed)
        self._dims[Constants.Observability.DIM_OUTCOME] = "Succeeded" if success else "Failed"
        return duration_ms, success, self._dims


def code_marker(name: str):
    """Stamp a stable telemetry name onto a CodeMarker subclass."""

    def _wrap(cls):
        cls.__marker_name__ = name
        return cls

    return _wrap


class CodeMarker:
    """
    Base class — subclass and decorate with `@code_marker("...")`.
    The class itself is the singleton; no instantiation needed.
    """

    @classmethod
    def name(cls) -> str:
        return getattr(cls, "__marker_name__", cls.__qualname__)

    # ------------------------------------------------------------------ #
    # execute / execute_async — the one and only public entry points.
    # ------------------------------------------------------------------ #
    @classmethod
    def execute(cls, action: Callable[[Scope], T]) -> T:
        scope = Scope(cls.name())
        raised = False
        try:
            return action(scope)
        except BaseException:
            raised = True
            raise
        finally:
            cls._emit(scope, raised)

    @classmethod
    async def execute_async(cls, action: Callable[[Scope], Awaitable[T]]) -> T:
        scope = Scope(cls.name())
        raised = False
        try:
            result = action(scope)
            if inspect.isawaitable(result):
                return await result  # type: ignore[no-any-return]
            return result  # tolerate sync actions
        except BaseException:
            raised = True
            raise
        finally:
            cls._emit(scope, raised)

    # ------------------------------------------------------------------ #
    # Sink dispatch — kept tiny. Override in a subclass if you want
    # per-marker routing instead of the global registry.
    # ------------------------------------------------------------------ #
    @classmethod
    def _emit(cls, scope: Scope, raised: bool) -> None:
        from .registry import resolve_sink

        duration_ms, success, dims = scope._finalize(raised)
        sink = resolve_sink()
        if sink is None:
            return
        event = {
            "name": scope.name,
            "duration_ms": duration_ms,
            "success": success,
            "dimensions": dims,
        }
        try:
            sink.emit(event)
        except Exception:
            # Never let a bad sink break the caller.
            pass
