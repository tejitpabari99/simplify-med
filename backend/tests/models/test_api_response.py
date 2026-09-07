import pytest


def test_api_response_error_round_trip():
    from models.api_response import ApiResponse, ErrorDetail, StatusEnum
    detail = ErrorDetail(
        code="INTERNAL_ERROR", message="msg", details="det",
        timestamp="2026-01-01T00:00:00Z", path="/test"
    )
    resp = ApiResponse(status=StatusEnum.error, error=detail, requestId="req-1")
    d = resp.to_dict()
    assert d["status"] == "error"
    assert d["error"]["code"] == "INTERNAL_ERROR"
    assert d["requestId"] == "req-1"
    resp2 = ApiResponse.from_dict(d)
    assert resp2.error.code == "INTERNAL_ERROR"


def test_api_response_path_is_optional():
    from models.api_response import ApiResponse, ErrorDetail, StatusEnum
    detail = ErrorDetail(code="TIMEOUT", message="timed out", details="",
                         timestamp="2026-01-01T00:00:00Z")
    resp = ApiResponse(status=StatusEnum.error, error=detail)
    d = resp.to_dict()
    assert d["error"]["path"] is None


def test_api_response_extra_field_raises():
    from models.api_response import ApiResponse
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ApiResponse(status="error", unknown_field="x")


def test_status_enum_values():
    from models.api_response import StatusEnum
    assert set(e.value for e in StatusEnum) == {"error", "success", "not_started", "processing", "completed"}
