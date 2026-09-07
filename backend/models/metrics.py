"""Metrics model for pipeline run telemetry."""

from datetime import datetime, timezone

from .base import JsonModel


class Metrics(JsonModel):
    """Tracks timing and metadata for a single pipeline run.

    Not versioned — always uses the latest shape. Mutated in-place as the
    pipeline progresses (total_duration_ms, saved_id).
    """

    session_id: str
    pipeline_version: str  # always Constants.Pipeline.PIPELINE_VERSION ("v1-2")
    input_type: str  # "file" | "text"
    created_at: str  # ISO8601
    total_duration_ms: float | None = None
    saved_id: str | None = None

    @classmethod
    def start(cls, session_id: str, pipeline_version: str, input_type: str) -> "Metrics":
        """Create a Metrics instance stamped with the current UTC time.

        Args:
            session_id: Unique identifier for this session.
            pipeline_version: Pipeline version string (always "v1-2").
            input_type: One of "file" or "text".

        Returns:
            New Metrics instance with created_at set and durations at defaults.
        """
        return cls(
            session_id=session_id,
            pipeline_version=pipeline_version,
            input_type=input_type,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
