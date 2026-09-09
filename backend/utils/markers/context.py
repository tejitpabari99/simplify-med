"""
Optional helper: bundle dimensions you commonly want to push into a scope.

Use it like:

    ctx = Context(correlation_id=req.id, user_id=user.id, dimensions={"region": "us"})
    Marker.execute(lambda scope: ctx.apply(scope) or do_work(scope))

It's intentionally schema-less — drop in whatever keys make sense for your
service. The well-known keys (`correlation_id`, `user_id`, `status_code`)
just save you a tiny bit of typing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from utils.constants import Constants
from .marker import Scope


@dataclass
class Context:
    correlation_id: Optional[str] = None
    user_id: Optional[str] = None
    status_code: Optional[int] = None
    dimensions: Dict[str, Any] = field(default_factory=dict)

    def apply(self, scope: Scope) -> None:
        """Push every non-empty field onto the scope."""
        if self.correlation_id:
            scope.add(Constants.Observability.DIM_CORRELATION_ID, self.correlation_id)
        if self.user_id:
            scope.add("UserId", self.user_id)
        if self.status_code is not None:
            scope.add(Constants.Observability.DIM_STATUS_CODE, str(self.status_code))
        scope.add_many(self.dimensions)


def _g(name: str, default=None):
    try:
        from flask import g
        return getattr(g, name, default)
    except (RuntimeError, ImportError):
        return default


@dataclass
class SimplifyContext:
    """Standard Simplify dimensions, sourced from flask.g, applied to every scope."""
    function: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_g(cls, function: Optional[str] = None, **extra) -> "SimplifyContext":
        return cls(function=function, extra=extra)

    def apply(self, scope: Scope) -> None:
        scope.add("session_id", _g("session_id"))
        scope.add("user_id", _g("user_id"))
        scope.add("function", self.function)
        scope.add("care_plan_version", _g("care_plan_version"))
        scope.add("grading_version", _g("grading_version"))
        scope.add("input_version", _g("input_version"))
        # "simplify-backend" hasn't been a real Cloud Run service since the app split
        # into juno-api/juno-worker. K_SERVICE is set by Cloud Run to whichever of those
        # is actually running, so prefer that (same idiom as observability/telemetry.py's
        # resource "service.name"); SERVICE_NAME_DEFAULT is the last-resort fallback for
        # non-Cloud-Run environments (e.g. local dev) where K_SERVICE isn't set.
        scope.add(
            "service",
            _g("service") or os.getenv(Constants.EnvVars.K_SERVICE, Constants.Observability.SERVICE_NAME_DEFAULT),
        )
        scope.add("environment", _g("environment") or "production")
        scope.add_many(self.extra)
