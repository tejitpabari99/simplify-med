"""
errors/exceptions.py — Unified exception classes, classifiers, and response builder.

This is the LOGIC layer for the Simplify error system (errors/codes.py is the DATA layer).

Provides:
  - _SafeDict, _safe_format: safe template formatting helpers
  - SimplifyError: structured pipeline exception carrying an ErrorCode
  - (Vertex per-system error classes and their classify() classmethods live in
    errors/vertex_errors.py, not in this module.)
  - classify_finish_reason: map FinishReason strings → ErrorCode
  - _classify_exc: internal classifier (SimplifyError → Vertex → fallback)
  - make_error_response: canonical ApiResponse builder (the ONE response builder)
  - build_error_data: Firestore-ready error_data dict for fail_job calls
  - build_error_data_from_exc: classify any exception → Firestore error_data dict
  - handle_exception: classify any exception → Flask-ready (response_dict, status_code)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from errors.codes import ERROR_CATALOG, ErrorCode, ErrorInfo
from models.api_response import ApiResponse, ErrorDetail, StatusEnum

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# _SafeDict / _safe_format — safe template formatting helpers
# ---------------------------------------------------------------------------

class _SafeDict(dict):
    """Substitute missing keys with their placeholder text to avoid KeyError."""
    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


def _safe_format(template: str, vars: dict) -> str:
    return template.format_map(_SafeDict(vars))


# ---------------------------------------------------------------------------
# SimplifyError — structured pipeline exception
# ---------------------------------------------------------------------------

class SimplifyError(Exception):
    """
    Structured pipeline exception carrying an ErrorCode.

    Raised by the LLM client and pipeline stages to signal a known failure
    class (e.g. token-limit hit, Vertex quota exceeded) with rich metadata.
    The error_code drives the user_hint, retryable flag, and HTTP status
    surfaced to the client.
    """

    def __init__(
        self,
        error_code: ErrorCode,
        detail: str = "",
        original: Exception | None = None,
    ) -> None:
        self.error_code = error_code
        self.info: ErrorInfo = ERROR_CATALOG[error_code]
        self.detail = detail
        self.original = original
        super().__init__(self.info.message)


# ---------------------------------------------------------------------------
# classify_finish_reason — map FinishReason strings → ErrorCode
# ---------------------------------------------------------------------------

_FINISH_REASON_MAP: dict[str, ErrorCode] = {
    "MAX_TOKENS":              ErrorCode.LLM_MAX_TOKENS,
    "SAFETY":                  ErrorCode.LLM_SAFETY_BLOCKED,
    "RECITATION":              ErrorCode.LLM_RECITATION_BLOCKED,
    "OTHER":                   ErrorCode.LLM_FINISH_OTHER,
    "BLOCKLIST":               ErrorCode.LLM_BLOCKLIST,
    "PROHIBITED_CONTENT":      ErrorCode.LLM_PROHIBITED_CONTENT,
    "SPII":                    ErrorCode.LLM_SPII,
    "MALFORMED_FUNCTION_CALL": ErrorCode.LLM_MALFORMED_FUNCTION_CALL,
}


def classify_finish_reason(finish_reason_str: str) -> ErrorCode:
    """
    Map a FinishReason string to an ErrorCode.

    Accepts either the enum ``.name`` (e.g. ``"MAX_TOKENS"``) or the
    string value — both are compared case-insensitively.
    Falls back to ``ErrorCode.LLM_FINISH_OTHER`` for unrecognised values.
    """
    return _FINISH_REASON_MAP.get(finish_reason_str.upper(), ErrorCode.LLM_FINISH_OTHER)


# ---------------------------------------------------------------------------
# Internal classifier
# ---------------------------------------------------------------------------

def _classify_exc(exc: Exception) -> tuple[ErrorCode, str]:
    """
    Return ``(error_code, detail_str)`` for any exception.

    Priority:
    1. SimplifyError — already classified; use its error_code and detail.
    2. google.api_core.exceptions.GoogleAPICallError → VertexAPIError.classify.
    3. Everything else → UNKNOWN_ERROR.
    """
    if isinstance(exc, SimplifyError):
        detail = exc.detail or str(exc.original or exc)
        return exc.error_code, detail

    # Google API errors — deferred import avoids a module-level cycle with
    # errors.vertex_errors (which imports SimplifyError from this module).
    try:
        from google.api_core import exceptions as _gexc
        from errors.vertex_errors import VertexAPIError
        if isinstance(exc, _gexc.GoogleAPICallError):
            return VertexAPIError.classify(exc), str(exc)
    except ImportError:
        pass

    return ErrorCode.UNKNOWN_ERROR, str(exc)


# ---------------------------------------------------------------------------
# make_error_response — canonical ApiResponse builder
# ---------------------------------------------------------------------------

def make_error_response(
    code: ErrorCode,
    path: str | None = None,
    details_vars: dict | None = None,
    requestId: str | None = None,
    user_hint: str | None = None,
    retryable: bool | None = None,
) -> ApiResponse:
    """Build a structured ApiResponse for an error and log it."""
    catalog_entry = ERROR_CATALOG[code]
    details = _safe_format(catalog_entry.details_template, details_vars or {})
    if requestId is None:
        try:
            from flask import g
            requestId = getattr(g, "session_id", None)
        except RuntimeError:
            requestId = None
    timestamp = datetime.now(timezone.utc).isoformat()
    error_detail = ErrorDetail(
        code=code.value,
        message=catalog_entry.message,
        details=details or None,
        timestamp=timestamp,
        path=path,
        user_hint=user_hint if user_hint is not None else catalog_entry.user_hint,
        retryable=retryable if retryable is not None else catalog_entry.retryable,
    )
    logger.error("error_response", extra={"error_code": code.value, "path": path, "request_id": requestId})
    return ApiResponse(status=StatusEnum.error, error=error_detail, requestId=requestId)


# ---------------------------------------------------------------------------
# build_error_data — Firestore-ready dict for fail_job
# ---------------------------------------------------------------------------

def build_error_data(error_code: ErrorCode, detail: str = "", **template_vars) -> dict:
    """
    Build the error_data dict written to Firestore on job failure.

    Honors ``ERROR_CATALOG[error_code].details_template`` the same way
    ``make_error_response`` (the HTTP path) does, rather than writing
    caller-supplied ``detail`` text straight into ``error_data.details``:

    - An INTERNAL error (empty ``details_template``, e.g.
      PIPELINE_VALIDATION_FAILED, LLM_MAX_TOKENS, UNKNOWN_ERROR, FILE_PARSE_FAILED)
      never gets a ``details`` value, regardless of what `detail` holds --
      the owner requirement is that internal failures surface only a
      generic message (``message``/`user_hint`, both static, curated text)
      to the user. This is also defense in depth: even a SimplifyError's
      own `detail` (curated by our code) could carry patient-derived text
      forwarded from an upstream exception message (e.g. a Pydantic
      ValidationError's `str(e)`, embedding the invalid value) -- see
      care_plan/pipeline.py's `_validation_error_detail` for the source-side
      fix; this is the second, structural layer of the same defense.
    - A USER error (non-empty ``details_template``, e.g.
      UNSUPPORTED_FILE_TYPE, JOB_TIMEOUT, PIPELINE_ERROR) gets that template
      safely expanded via ``_safe_format`` -- never the raw `detail` string
      verbatim -- with `detail` filling a template's ``{detail}``
      placeholder (PIPELINE_ERROR, UNAUTHORIZED) and any extra
      ``template_vars`` filling the rest (e.g. ``stage=`` for JOB_TIMEOUT).
      A placeholder with no matching var is left as literal ``{name}`` text
      (``_safe_format``'s existing missing-key behavior) rather than raising
      or leaking anything -- the same fallback the HTTP path already
      exhibits for a generically-caught SimplifyError with no details_vars.

    Full exception detail remains available server-side only, via
    `logger.exception` at the call sites that lead here -- never through
    this dict.
    """
    info = ERROR_CATALOG[error_code]
    if info.details_template:
        details = _safe_format(info.details_template, {"detail": detail, **template_vars}) or None
    else:
        details = None
    return {
        "code": info.code,
        "message": info.message,
        "user_hint": info.user_hint,
        "retryable": info.retryable,
        "details": details,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def build_error_data_from_exc(exc: Exception) -> dict:
    """
    Classify any exception and return a Firestore-ready ``error_data`` dict.

    Shorthand for ``build_error_data(*_classify_exc(exc))``. Any redaction of
    the classified `detail` (e.g. for UNKNOWN_ERROR, or any other code whose
    catalog entry has no ``details_template``) is handled uniformly inside
    `build_error_data` itself -- see its docstring; this function no longer
    needs its own special case.
    """
    error_code, detail = _classify_exc(exc)
    return build_error_data(error_code, detail)


# ---------------------------------------------------------------------------
# handle_exception — Flask-ready catch-all
# ---------------------------------------------------------------------------

def handle_exception(exc: Exception) -> tuple[dict, int]:
    """
    Classify any exception and return a Flask-ready ``(response_dict, status_code)`` tuple.
    """
    error_code, detail = _classify_exc(exc)
    info = ERROR_CATALOG[error_code]
    resp = make_error_response(error_code, details_vars={"detail": detail})
    return resp.model_dump(), info.http_status
