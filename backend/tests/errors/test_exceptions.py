def test_make_error_response_returns_api_response():
    from errors import make_error_response, ErrorCode
    from models.api_response import ApiResponse, StatusEnum
    resp = make_error_response(ErrorCode.RESOURCE_NOT_FOUND, path="/test")
    assert isinstance(resp, ApiResponse)
    assert resp.status == StatusEnum.error
    assert resp.error.code == "RESOURCE_NOT_FOUND"

def test_make_error_response_autofills_user_hint_from_catalog():
    from errors import make_error_response, ErrorCode
    resp = make_error_response(ErrorCode.VERTEX_QUOTA_EXCEEDED)
    assert resp.error.user_hint is not None
    assert len(resp.error.user_hint) > 0

def test_make_error_response_override_user_hint():
    from errors import make_error_response, ErrorCode
    resp = make_error_response(ErrorCode.PIPELINE_ERROR, user_hint="Custom hint")
    assert resp.error.user_hint == "Custom hint"

def test_make_error_response_autofills_retryable_from_catalog():
    from errors import make_error_response, ErrorCode
    resp = make_error_response(ErrorCode.VERTEX_QUOTA_EXCEEDED)
    assert resp.error.retryable is True

def test_make_error_response_retryable_override():
    from errors import make_error_response, ErrorCode
    resp = make_error_response(ErrorCode.VERTEX_QUOTA_EXCEEDED, retryable=False)
    assert resp.error.retryable is False

def test_make_error_response_no_flask_context_does_not_raise():
    from errors import make_error_response, ErrorCode
    resp = make_error_response(ErrorCode.TIMEOUT)
    assert resp.requestId is None

def test_build_error_data_includes_all_keys():
    from errors import build_error_data, ErrorCode
    from datetime import datetime
    result = build_error_data(ErrorCode.JOB_TIMEOUT)
    assert "timestamp" in result
    assert "code" in result
    assert "message" in result
    assert "user_hint" in result
    assert "retryable" in result
    assert "details" in result
    datetime.fromisoformat(result["timestamp"])

def test_build_error_data_uses_details_key():
    """PIPELINE_ERROR's catalog template ("Unexpected error during
    processing: {detail}") has a `{detail}` placeholder, so `detail` is
    safely expanded into it -- unlike an internal/empty-template code
    (see test_build_error_data_blanks_details_for_internal_code below),
    this is a genuine user-facing detail-template code."""
    from errors import build_error_data, ErrorCode
    result = build_error_data(ErrorCode.PIPELINE_ERROR, detail="some detail")
    assert "details" in result
    assert "detail" not in result
    assert result["details"] == "Unexpected error during processing: some detail"


def test_build_error_data_fills_named_template_vars():
    """Non-`detail`-named placeholders (e.g. JOB_TIMEOUT's `{stage}`) are
    filled from `**template_vars`, not the `detail` positional string."""
    from errors import build_error_data, ErrorCode
    result = build_error_data(ErrorCode.JOB_TIMEOUT, stage=3)
    assert result["details"] == "Job exceeded the worker time limit at stage 3"


def test_build_error_data_blanks_details_for_internal_code():
    """Finding 1a regression: a code whose catalog entry has an empty
    `details_template` (an internal error, e.g. PIPELINE_VALIDATION_FAILED)
    must never surface a `detail` value into error_data.details, even when
    a caller passes one -- the owner requirement is that internal failures
    surface only the generic, static `message`/`user_hint` to the user."""
    from errors import build_error_data, ErrorCode
    result = build_error_data(ErrorCode.PIPELINE_VALIDATION_FAILED, detail="PATIENT_MARKER_XYZ")
    assert result["details"] is None


def test_build_error_data_from_exc_pipeline_validation_failed_strips_marker():
    """Finding 1a regression (item 2): build_error_data_from_exc for a
    PIPELINE_VALIDATION_FAILED SimplifyError whose detail contains
    patient-derived content (a marker string standing in for real clinical
    text) must not let that content reach the returned dict's `details`."""
    from errors import build_error_data_from_exc, SimplifyError, ErrorCode
    try:
        raise SimplifyError(ErrorCode.PIPELINE_VALIDATION_FAILED, detail="PATIENT_MARKER_XYZ")
    except SimplifyError as exc:
        result = build_error_data_from_exc(exc)
    assert result["code"] == "PIPELINE_VALIDATION_FAILED"
    assert result["details"] is None
    assert "PATIENT_MARKER_XYZ" not in str(result)


def test_build_error_data_user_error_code_keeps_user_facing_details():
    """Finding 1a regression (item 3): a user-error code (non-empty
    details_template) still gets its user-facing details through
    build_error_data_from_exc."""
    from errors import build_error_data_from_exc, SimplifyError, ErrorCode
    try:
        raise SimplifyError(ErrorCode.UNSUPPORTED_FILE_TYPE, detail="extension: .exe")
    except SimplifyError as exc:
        result = build_error_data_from_exc(exc)
    assert result["code"] == "UNSUPPORTED_FILE_TYPE"
    assert result["details"] is not None
    assert "PDF, TXT, DOCX, or HTML" in result["details"]

def test_build_error_data_from_exc_simplify_error():
    from errors import build_error_data_from_exc, SimplifyError, ErrorCode
    try:
        raise SimplifyError(ErrorCode.LLM_MAX_TOKENS, "too big")
    except SimplifyError as exc:
        result = build_error_data_from_exc(exc)
    assert result["code"] == "LLM_MAX_TOKENS"
    assert result.get("user_hint") is not None


def test_build_error_data_from_exc_simplify_error_detail_is_preserved():
    """A SimplifyError's own `detail` IS curated by our own code (unlike a raw,
    unclassified exception's message), but whether it reaches
    error_data.details is still gated by the catalog's details_template
    (Finding 1a): FILE_PARSE_FAILED's template is empty (an internal error --
    its static `message`/`user_hint` already cover the user-facing case), so
    `details` is blanked here just as it is for any other empty-template
    code, uniformly with the HTTP path (make_error_response)."""
    from errors import build_error_data_from_exc, SimplifyError, ErrorCode
    try:
        raise SimplifyError(ErrorCode.FILE_PARSE_FAILED, "notes.pdf could not be read")
    except SimplifyError as exc:
        result = build_error_data_from_exc(exc)
    assert result["details"] is None


def test_build_error_data_from_exc_unclassified_exception_strips_details():
    """Regression for Finding 10: an unclassified (UNKNOWN_ERROR) exception's
    raw message must never reach error_data.details, which the frontend's
    live listener reads -- some exception messages (e.g. certain Pydantic
    ValidationErrors) embed the actual invalid value. The full exception is
    still captured server-side via logger.exception at the call site."""
    from errors import build_error_data_from_exc
    result = build_error_data_from_exc(ValueError("some possibly-sensitive internal detail"))
    assert result["code"] == "UNKNOWN_ERROR"
    assert result["details"] is None

def test_handle_exception_unclassified_returns_500():
    from errors import handle_exception
    result, status = handle_exception(Exception("boom"))
    assert status == 500


def test_vertex_api_error_classify_type_map():
    from errors import ErrorCode, VertexAPIError
    from google.api_core import exceptions as gexc

    cases = [
        (gexc.ResourceExhausted("x"), ErrorCode.VERTEX_QUOTA_EXCEEDED),
        (gexc.DeadlineExceeded("x"), ErrorCode.VERTEX_DEADLINE_EXCEEDED),
        (gexc.InvalidArgument("x"), ErrorCode.VERTEX_INVALID_ARGUMENT),
        (gexc.PermissionDenied("x"), ErrorCode.VERTEX_PERMISSION_DENIED),
        (gexc.NotFound("x"), ErrorCode.VERTEX_NOT_FOUND),
        (gexc.ServiceUnavailable("x"), ErrorCode.VERTEX_SERVICE_UNAVAILABLE),
        (gexc.InternalServerError("x"), ErrorCode.VERTEX_INTERNAL_ERROR),
        (gexc.Unauthenticated("x"), ErrorCode.VERTEX_UNAUTHENTICATED),
        (gexc.Aborted("x"), ErrorCode.VERTEX_ABORTED),
    ]
    for exc, expected_code in cases:
        assert VertexAPIError.classify(exc) == expected_code


def test_vertex_api_error_classify_unmapped_type_returns_unknown():
    from errors import ErrorCode, VertexAPIError
    assert VertexAPIError.classify(ValueError("not a google exception")) == ErrorCode.UNKNOWN_ERROR


def test_vertex_api_error_is_simplify_error():
    from errors import SimplifyError, ErrorCode, VertexAPIError
    from google.api_core import exceptions as gexc
    original = gexc.ResourceExhausted("quota")
    exc = VertexAPIError(original)
    assert isinstance(exc, SimplifyError)
    assert exc.error_code == ErrorCode.VERTEX_QUOTA_EXCEEDED
    assert exc.original is original


def test_missing_job_config_error_is_simplify_error():
    from errors import SimplifyError, ErrorCode
    from utils.cloud_tasks import MissingJobConfigError
    exc = MissingJobConfigError("CLOUD_TASKS_QUEUE")
    assert isinstance(exc, SimplifyError)
    assert exc.error_code == ErrorCode.INTERNAL_ERROR


