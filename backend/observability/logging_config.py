"""
Structured logging configuration for Google Cloud Logging integration.

On Cloud Run, JSON-formatted log lines written to stdout are automatically
ingested by Cloud Logging and fully searchable in the Google Cloud Console.

Each log entry includes:
- message        — the log message
- severity       — INFO, WARNING, ERROR, etc.
- session_id     — the X-Session-Id from the client (groups a user session)
- trace_id       — OpenTelemetry trace ID (links to Cloud Trace)
- span_id        — OpenTelemetry span ID
- logger         — Python logger name (module)

Usage:
    from logging_config import setup_logging
    setup_logging()  # call once at startup

    import logging
    logger = logging.getLogger(__name__)
    logger.info("Processing started", extra={"session_id": "abc-123"})
"""

import json
import logging
import os
import sys

from opentelemetry import trace

from utils.constants import Constants

_SENTINEL = object()


class SessionIdFilter(logging.Filter):
    """
    Logging filter that automatically injects session_id from Flask's g context.
    This means route code can simply call logger.info("message") without needing
    to pass extra={"session_id": ...} every time.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            from flask import g
            record.session_id = getattr(g, "session_id", None)
        except RuntimeError:
            # Outside Flask request context
            record.session_id = None
        return True


class StructuredJsonFormatter(logging.Formatter):
    """
    Formats log records as single-line JSON objects.

    Cloud Logging on Cloud Run automatically parses JSON from stdout and maps:
    - "severity" → Cloud Logging severity
    - "message"  → log text
    - "logging.googleapis.com/trace" → trace correlation
    - All other keys → searchable in jsonPayload.*
    """

    def __init__(self):
        super().__init__()
        self.gcp_project_id = os.getenv("GCP_PROJECT_ID", "")

    def format(self, record: logging.LogRecord) -> str:
        # Base log entry
        log_entry: dict = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }

        # Add session_id if present in the record's extra fields
        session_id = getattr(record, "session_id", None)
        if session_id:
            log_entry["session_id"] = session_id

        # Add whitelisted extra fields (marker events, version fields, metrics, etc.)
        for key in Constants.Observability.LOG_EXTRA_KEYS:
            val = getattr(record, key, _SENTINEL)
            if val is not _SENTINEL:
                log_entry[key] = val

        # Add OpenTelemetry trace context
        span_context = trace.get_current_span().get_span_context()
        if span_context and span_context.is_valid:
            trace_id_hex = format(span_context.trace_id, "032x")
            span_id_hex = format(span_context.span_id, "016x")

            log_entry["trace_id"] = trace_id_hex
            log_entry["span_id"] = span_id_hex

            # Google Cloud Logging trace correlation format
            # This links log entries to the corresponding Cloud Trace trace
            if self.gcp_project_id:
                log_entry["logging.googleapis.com/trace"] = (
                    f"projects/{self.gcp_project_id}/traces/{trace_id_hex}"
                )
                log_entry["logging.googleapis.com/spanId"] = span_id_hex

        # Include exception info if present
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


def setup_logging():
    """
    Configure the root Python logger with structured JSON output.

    Call this once at application startup (before any logging is done).
    In production (Cloud Run), this outputs JSON to stdout.
    In development, it outputs human-readable formatted logs.
    """
    is_production = os.getenv("K_SERVICE") is not None

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Remove any existing handlers to avoid duplicate log lines
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)

    if is_production:
        handler.setFormatter(StructuredJsonFormatter())
    else:
        # Dev-friendly format that still shows session_id when present
        handler.setFormatter(logging.Formatter(
            "[%(asctime)s] %(levelname)s %(name)s — %(message)s"
        ))

    # Auto-inject session_id from Flask g context into every log record
    handler.addFilter(SessionIdFilter())

    root_logger.addHandler(handler)

    # Quieten noisy third-party loggers
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)
    logging.getLogger("opentelemetry").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
