"""
Tests for Task 11 — StructuredJsonFormatter extra-field whitelist pass-through.

Verifies that known marker/version/metric extra fields are serialized into the
JSON log entry, that unknown keys are NOT leaked, and that existing OTel
trace-context behavior is preserved.
"""

import json
import logging
from unittest.mock import MagicMock, patch


from observability.logging_config import StructuredJsonFormatter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_record(msg="test message", extra=None):
    """Return a LogRecord with optional extra attributes set."""
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=msg,
        args=(),
        exc_info=None,
    )
    if extra:
        for k, v in extra.items():
            setattr(record, k, v)
    return record


def fmt(record):
    """Format a record through StructuredJsonFormatter and return parsed dict."""
    return json.loads(StructuredJsonFormatter().format(record))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_extra_fields_serialized():
    """All whitelisted extra keys present on the record land in the JSON output."""
    extra = {
        "operation": "care_plan.simplify_language",
        "duration_ms": 123,
        "metric": True,
        "metric_type": "marker",
        "function": "simplify_language",
        "care_plan_version": "1.2",
    }
    result = fmt(make_record(extra=extra))
    for key, value in extra.items():
        assert key in result, f"Expected '{key}' in log entry"
        assert result[key] == value, f"Expected {key}={value!r}, got {result[key]!r}"


def test_metric_true_preserved():
    """Boolean True is preserved exactly (not coerced to a string)."""
    result = fmt(make_record(extra={"metric": True}))
    assert result["metric"] is True


def test_success_bool_preserved():
    """Boolean False is preserved exactly (falsy sentinel check must not drop it)."""
    result = fmt(make_record(extra={"success": False}))
    assert "success" in result
    assert result["success"] is False


def test_unknown_extra_not_leaked():
    """Keys not in the whitelist must not appear in the JSON output."""
    result = fmt(make_record(extra={"some_random_key_not_in_whitelist": "foo"}))
    assert "some_random_key_not_in_whitelist" not in result


def test_trace_fields_still_present():
    """Existing OTel trace-context serialization is not broken by the new code."""
    # Build a realistic span context with a valid trace_id and span_id
    mock_span_context = MagicMock()
    mock_span_context.is_valid = True
    mock_span_context.trace_id = 0xABCDEF1234567890ABCDEF1234567890
    mock_span_context.span_id = 0x1234567890ABCDEF

    mock_span = MagicMock()
    mock_span.get_span_context.return_value = mock_span_context

    formatter = StructuredJsonFormatter()
    formatter.gcp_project_id = "my-project"

    with patch("observability.logging_config.trace.get_current_span", return_value=mock_span):
        result = json.loads(formatter.format(make_record()))

    assert "trace_id" in result
    assert "logging.googleapis.com/trace" in result
