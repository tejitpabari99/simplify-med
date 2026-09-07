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
    from errors import build_error_data, ErrorCode
    result = build_error_data(ErrorCode.JOB_TIMEOUT, detail="some detail")
    assert "details" in result
    assert "detail" not in result
    assert result["details"] == "some detail"

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
    unclassified exception's message) and must still reach error_data.details."""
    from errors import build_error_data_from_exc, SimplifyError, ErrorCode
    try:
        raise SimplifyError(ErrorCode.FILE_PARSE_FAILED, "notes.pdf could not be read")
    except SimplifyError as exc:
        result = build_error_data_from_exc(exc)
    assert result["details"] == "notes.pdf could not be read"


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


