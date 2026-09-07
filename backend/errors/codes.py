"""
errors/codes.py — Unified source of truth for all Simplify backend error metadata.

This file is PURE DATA. No logic, no imports of Flask/Firestore/Vertex SDK.

It defines:
  - ErrorInfo dataclass: per-error metadata
  - ErrorCode enum: all canonical error identifiers
  - ERROR_CATALOG: lookup dict tying ErrorCode -> ErrorInfo

Categories
----------
1. LLM Generation       — Vertex AI FinishReason variants + JSON parse failure
2. Vertex AI API        — google.api_core.exceptions mapped to HTTP semantics
3. Pipeline/Processing  — file parsing, validation, document-level failures
4. Auth                 — authentication and authorization errors
5. Resource             — resource-level 404/403 errors
6. Input                — request input validation errors
7. Timeout              — generic HTTP timeout
8. System               — catch-all and routing errors
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


# ---------------------------------------------------------------------------
# ErrorInfo — metadata for a single error class
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ErrorInfo:
    """Immutable metadata bundle for one error class."""

    code: str
    """
    Canonical short uppercase string, e.g. ``"LLM_MAX_TOKENS"``.
    Matches the ErrorCode member name exactly so callers can round-trip it.
    """

    http_status: int
    """HTTP status code the API layer should return for this error."""

    message: str
    """
    Developer-facing description.
    Explains the root cause in technical terms.
    """

    user_hint: str
    """
    Actionable plain-English message suitable for display in the client UI.
    Written for a non-technical end user.
    """

    retryable: bool
    """
    True if the same request is likely to succeed on a subsequent attempt
    (e.g., transient network error, quota reset). False for permanent failures.
    """

    details_template: str = ""
    """
    Format string for structured detail expansion.
    Uses str.format_map semantics; missing keys are left as-is.
    """


# ---------------------------------------------------------------------------
# ErrorCode — canonical identifiers (unified)
# ---------------------------------------------------------------------------

class ErrorCode(StrEnum):
    """
    All recognized error codes, grouped by category.

    Each member's string value equals its name so ErrorCode.LLM_MAX_TOKENS == "LLM_MAX_TOKENS".

    UNKNOWN_ERROR and INTERNAL_ERROR both exist deliberately (different use sites).
    """

    # ------------------------------------------------------------------
    # 1. LLM Generation — Vertex AI FinishReason variants
    #    Source: vertexai.preview.generative_models.FinishReason
    # ------------------------------------------------------------------

    LLM_MAX_TOKENS = "LLM_MAX_TOKENS"
    """Generation stopped because the output hit the max_output_tokens limit."""

    LLM_SAFETY_BLOCKED = "LLM_SAFETY_BLOCKED"
    """Generation stopped because the response triggered a safety filter (FinishReason.SAFETY)."""

    LLM_RECITATION_BLOCKED = "LLM_RECITATION_BLOCKED"
    """Generation stopped due to potential verbatim recitation of training data (FinishReason.RECITATION)."""

    LLM_FINISH_OTHER = "LLM_FINISH_OTHER"
    """Generation ended for an unspecified reason (FinishReason.OTHER)."""

    LLM_BLOCKLIST = "LLM_BLOCKLIST"
    """Content matched an operator-configured term blocklist (FinishReason.BLOCKLIST)."""

    LLM_PROHIBITED_CONTENT = "LLM_PROHIBITED_CONTENT"
    """Content was flagged as prohibited by platform policy (FinishReason.PROHIBITED_CONTENT)."""

    LLM_SPII = "LLM_SPII"
    """
    Generation blocked because the response contained sensitive personally
    identifiable information (FinishReason.SPII).
    """

    LLM_MALFORMED_FUNCTION_CALL = "LLM_MALFORMED_FUNCTION_CALL"
    """
    Model emitted a function call that did not conform to the declared schema
    (FinishReason.MALFORMED_FUNCTION_CALL).
    """

    LLM_NO_CANDIDATES = "LLM_NO_CANDIDATES"
    """Model returned an empty candidates list; generation produced no output."""

    LLM_INVALID_JSON = "LLM_INVALID_JSON"
    """Model output could not be parsed as valid JSON after fence-stripping."""

    # ------------------------------------------------------------------
    # 2. Vertex AI API Errors
    #    Source: google.api_core.exceptions (gRPC/HTTP mapped)
    # ------------------------------------------------------------------

    VERTEX_QUOTA_EXCEEDED = "VERTEX_QUOTA_EXCEEDED"
    """API quota or rate limit exceeded (ResourceExhausted / HTTP 429)."""

    VERTEX_DEADLINE_EXCEEDED = "VERTEX_DEADLINE_EXCEEDED"
    """Vertex AI API call timed out server-side (DeadlineExceeded / HTTP 504)."""

    VERTEX_INVALID_ARGUMENT = "VERTEX_INVALID_ARGUMENT"
    """Request payload was rejected by the API as invalid (InvalidArgument / HTTP 400)."""

    VERTEX_PERMISSION_DENIED = "VERTEX_PERMISSION_DENIED"
    """Caller lacks IAM permission to invoke the Vertex AI endpoint (PermissionDenied / HTTP 403)."""

    VERTEX_NOT_FOUND = "VERTEX_NOT_FOUND"
    """Requested model or resource does not exist in the project/region (NotFound / HTTP 404)."""

    VERTEX_SERVICE_UNAVAILABLE = "VERTEX_SERVICE_UNAVAILABLE"
    """Vertex AI service is temporarily unavailable (ServiceUnavailable / HTTP 503)."""

    VERTEX_INTERNAL_ERROR = "VERTEX_INTERNAL_ERROR"
    """Vertex AI returned an internal server error (InternalServerError / HTTP 500->502)."""

    VERTEX_UNAUTHENTICATED = "VERTEX_UNAUTHENTICATED"
    """Request lacked valid credentials for the Vertex AI API (Unauthenticated / HTTP 401)."""

    VERTEX_ABORTED = "VERTEX_ABORTED"
    """Vertex AI aborted the operation, typically due to a concurrency conflict (Aborted / HTTP 503)."""

    # ------------------------------------------------------------------
    # 3. Pipeline / Processing Errors
    # ------------------------------------------------------------------

    FILE_PARSE_FAILED = "FILE_PARSE_FAILED"
    """An uploaded file could not be read or its text could not be extracted."""

    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    """The file extension or MIME type is not accepted by the pipeline."""

    EMPTY_DOCUMENT = "EMPTY_DOCUMENT"
    """The document produced no extractable text after parsing."""

    JOB_TIMEOUT = "JOB_TIMEOUT"
    """The individual job exceeded its allocated processing time."""

    PIPELINE_VALIDATION_FAILED = "PIPELINE_VALIDATION_FAILED"
    """Pydantic (or equivalent) validation of the LLM-structured output failed."""

    PIPELINE_ERROR = "PIPELINE_ERROR"
    """Unexpected error during pipeline processing."""

    # ------------------------------------------------------------------
    # 4. Auth
    # ------------------------------------------------------------------

    UNAUTHORIZED = "UNAUTHORIZED"
    """Authentication failed — invalid or expired token."""

    MISSING_AUTH_HEADER = "MISSING_AUTH_HEADER"
    """No Authorization header was present in the request."""

    MALFORMED_AUTH_HEADER = "MALFORMED_AUTH_HEADER"
    """The Authorization header did not match the expected format."""

    ANONYMOUS_ACCESS_FORBIDDEN = "ANONYMOUS_ACCESS_FORBIDDEN"
    """An anonymous (unauthenticated-identity) Firebase token was used against a
    route that requires a non-anonymous account. Anonymous tokens are only
    accepted on the /jobs routes."""

    # ------------------------------------------------------------------
    # 5. Resource
    # ------------------------------------------------------------------

    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    """The requested Firestore document or resource does not exist."""

    RESOURCE_FORBIDDEN = "RESOURCE_FORBIDDEN"
    """The caller does not own the requested resource."""

    # ------------------------------------------------------------------
    # 6. Input
    # ------------------------------------------------------------------

    INPUT_VALIDATION_ERROR = "INPUT_VALIDATION_ERROR"
    """The request body failed schema validation."""

    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    """The uploaded file exceeds the configured size limit."""

    # ------------------------------------------------------------------
    # 7. Timeout
    # ------------------------------------------------------------------

    TIMEOUT = "TIMEOUT"
    """Generic HTTP-level request timeout at the route layer."""

    # ------------------------------------------------------------------
    # 8. System / Catch-all
    # ------------------------------------------------------------------

    # UNKNOWN_ERROR: _classify_exc fallback for unclassified pipeline exceptions
    UNKNOWN_ERROR = "UNKNOWN_ERROR"
    """An unexpected error with no more specific classification."""

    # INTERNAL_ERROR: HTTP routes and Flask global error handlers
    INTERNAL_ERROR = "INTERNAL_ERROR"
    """Generic internal server error surfaced by HTTP routes and Flask error handlers."""

    ENDPOINT_NOT_FOUND = "ENDPOINT_NOT_FOUND"
    """No route matched the incoming HTTP method and path."""

    # ------------------------------------------------------------------
    # 9. Rate Limiting
    # ------------------------------------------------------------

    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    """The caller's IP has exceeded the per-hour simplification limit."""


# ---------------------------------------------------------------------------
# ERROR_CATALOG — main lookup table
# ---------------------------------------------------------------------------

ERROR_CATALOG: dict[ErrorCode, ErrorInfo] = {

    # ------------------------------------------------------------------
    # LLM Generation
    # ------------------------------------------------------------------

    ErrorCode.LLM_MAX_TOKENS: ErrorInfo(
        code="LLM_MAX_TOKENS",
        http_status=500,
        message=(
            "LLM generation stopped at the output token limit (FinishReason.MAX_TOKENS) "
            "before the response was complete. This is an output-length failure, not an "
            "input-length one -- see `detail` for the max_tokens value that was in effect "
            "and consider raising it for this call site."
        ),
        # NOTE: this is NOT a document-length problem -- it means the model's own
        # response was cut off while generating output, which can happen even for a
        # short input document. Do not blame document length here; that was the bug
        # (this error surfaced as "the document was too long" after every earlier
        # pipeline step had already run, which was both wrong and confusing).
        user_hint=(
            "Something went wrong while finishing the response. Please try again. "
            "If it keeps happening, try a smaller section of the document."
        ),
        retryable=True,
        details_template="",
    ),

    ErrorCode.LLM_SAFETY_BLOCKED: ErrorInfo(
        code="LLM_SAFETY_BLOCKED",
        http_status=422,
        message=(
            "LLM output was blocked by a Vertex AI safety filter (FinishReason.SAFETY). "
            "The prompt or generated content matched a configured harm category threshold."
        ),
        user_hint=(
            "The document could not be processed because it triggered a content safety check. "
            "Remove any flagged content and try again."
        ),
        retryable=False,
        details_template="",
    ),

    ErrorCode.LLM_RECITATION_BLOCKED: ErrorInfo(
        code="LLM_RECITATION_BLOCKED",
        http_status=422,
        message=(
            "LLM output was stopped due to potential verbatim recitation of training data "
            "(FinishReason.RECITATION)."
        ),
        user_hint=(
            "The document could not be processed due to a content policy restriction. "
            "Contact support if this continues."
        ),
        retryable=False,
        details_template="",
    ),

    ErrorCode.LLM_FINISH_OTHER: ErrorInfo(
        code="LLM_FINISH_OTHER",
        http_status=500,
        message=(
            "LLM generation ended for an unspecified reason (FinishReason.OTHER). "
            "No content was returned."
        ),
        user_hint=(
            "The AI model stopped unexpectedly. Please try again. "
            "If the problem persists, contact support."
        ),
        retryable=True,
        details_template="",
    ),

    ErrorCode.LLM_BLOCKLIST: ErrorInfo(
        code="LLM_BLOCKLIST",
        http_status=422,
        message=(
            "LLM output matched a term in the operator-configured blocklist "
            "(FinishReason.BLOCKLIST)."
        ),
        user_hint=(
            "The document contains restricted content and could not be processed. "
            "Contact support if you believe this is an error."
        ),
        retryable=False,
        details_template="",
    ),

    ErrorCode.LLM_PROHIBITED_CONTENT: ErrorInfo(
        code="LLM_PROHIBITED_CONTENT",
        http_status=422,
        message=(
            "LLM output was blocked because it was classified as prohibited content "
            "(FinishReason.PROHIBITED_CONTENT)."
        ),
        user_hint=(
            "The document contains content that cannot be processed under our usage policy. "
            "Contact support if you believe this is in error."
        ),
        retryable=False,
        details_template="",
    ),

    ErrorCode.LLM_SPII: ErrorInfo(
        code="LLM_SPII",
        http_status=422,
        message=(
            "LLM generation was blocked because the response contained sensitive personally "
            "identifiable information (FinishReason.SPII)."
        ),
        user_hint=(
            "The document could not be processed because the response contained sensitive "
            "personal information. Please review the document contents and try again."
        ),
        retryable=False,
        details_template="",
    ),

    ErrorCode.LLM_MALFORMED_FUNCTION_CALL: ErrorInfo(
        code="LLM_MALFORMED_FUNCTION_CALL",
        http_status=500,
        message=(
            "LLM emitted a function/tool call that did not conform to the declared schema "
            "(FinishReason.MALFORMED_FUNCTION_CALL). This is an internal prompt engineering issue."
        ),
        user_hint=(
            "An internal error occurred during AI processing. Please try again. "
            "If the problem persists, contact support."
        ),
        retryable=True,
        details_template="",
    ),

    ErrorCode.LLM_NO_CANDIDATES: ErrorInfo(
        code="LLM_NO_CANDIDATES",
        http_status=500,
        message=(
            "The Vertex AI model response contained no candidates. "
            "The generation may have been fully blocked before producing any output."
        ),
        user_hint=(
            "The AI model did not produce a response. Please try again. "
            "If the problem persists, contact support."
        ),
        retryable=True,
        details_template="",
    ),

    ErrorCode.LLM_INVALID_JSON: ErrorInfo(
        code="LLM_INVALID_JSON",
        http_status=500,
        message=(
            "The LLM returned output that could not be parsed as valid JSON after "
            "markdown fence-stripping. The model may have deviated from the required schema."
        ),
        user_hint=(
            "An internal error occurred while processing the AI response. "
            "Please try again."
        ),
        retryable=True,
        details_template="",
    ),

    # ------------------------------------------------------------------
    # Vertex AI API Errors
    # ------------------------------------------------------------------

    ErrorCode.VERTEX_QUOTA_EXCEEDED: ErrorInfo(
        code="VERTEX_QUOTA_EXCEEDED",
        http_status=429,
        message=(
            "Vertex AI API quota or rate limit exceeded (google.api_core.exceptions.ResourceExhausted). "
            "Too many requests in a short window or the project QPM/TPM quota is exhausted."
        ),
        user_hint=(
            "The system is temporarily busy. Please wait a moment and try again."
        ),
        retryable=True,
        details_template="",
    ),

    ErrorCode.VERTEX_DEADLINE_EXCEEDED: ErrorInfo(
        code="VERTEX_DEADLINE_EXCEEDED",
        http_status=504,
        message=(
            "The Vertex AI API call timed out before a response was received "
            "(google.api_core.exceptions.DeadlineExceeded)."
        ),
        user_hint=(
            "The request timed out. Please try again. "
            "If the document is very long, consider uploading a shorter version."
        ),
        retryable=True,
        details_template="",
    ),

    ErrorCode.VERTEX_INVALID_ARGUMENT: ErrorInfo(
        code="VERTEX_INVALID_ARGUMENT",
        http_status=400,
        message=(
            "The Vertex AI API rejected the request as invalid "
            "(google.api_core.exceptions.InvalidArgument). "
            "Likely a malformed prompt, unsupported parameter, or schema mismatch."
        ),
        user_hint=(
            "The request could not be processed due to an invalid parameter. "
            "Contact support if this continues."
        ),
        retryable=False,
        details_template="",
    ),

    ErrorCode.VERTEX_PERMISSION_DENIED: ErrorInfo(
        code="VERTEX_PERMISSION_DENIED",
        http_status=403,
        message=(
            "The service account lacks IAM permission to call the Vertex AI endpoint "
            "(google.api_core.exceptions.PermissionDenied). "
            "Check roles/aiplatform.user on the GCP project."
        ),
        user_hint=(
            "A configuration error prevented the system from processing your request. "
            "Contact support."
        ),
        retryable=False,
        details_template="",
    ),

    ErrorCode.VERTEX_NOT_FOUND: ErrorInfo(
        code="VERTEX_NOT_FOUND",
        http_status=404,
        message=(
            "The requested Vertex AI model or resource was not found in the configured "
            "project/region (google.api_core.exceptions.NotFound). "
            "Check VERTEX_AI_MODEL and GCP_LOCATION environment variables."
        ),
        user_hint=(
            "A configuration error prevented the system from reaching the AI model. "
            "Contact support."
        ),
        retryable=False,
        details_template="",
    ),

    ErrorCode.VERTEX_SERVICE_UNAVAILABLE: ErrorInfo(
        code="VERTEX_SERVICE_UNAVAILABLE",
        http_status=503,
        message=(
            "The Vertex AI service is temporarily unavailable "
            "(google.api_core.exceptions.ServiceUnavailable)."
        ),
        user_hint=(
            "The AI service is temporarily unavailable. Please try again in a few minutes."
        ),
        retryable=True,
        details_template="",
    ),

    ErrorCode.VERTEX_INTERNAL_ERROR: ErrorInfo(
        code="VERTEX_INTERNAL_ERROR",
        http_status=502,
        message=(
            "Vertex AI returned an internal server error "
            "(google.api_core.exceptions.InternalServerError)."
        ),
        user_hint=(
            "The AI service encountered an internal error. Please try again."
        ),
        retryable=True,
        details_template="",
    ),

    ErrorCode.VERTEX_UNAUTHENTICATED: ErrorInfo(
        code="VERTEX_UNAUTHENTICATED",
        http_status=401,
        message=(
            "The Vertex AI API call was rejected due to missing or invalid credentials "
            "(google.api_core.exceptions.Unauthenticated). "
            "Application Default Credentials may not be configured correctly."
        ),
        user_hint=(
            "A configuration error prevented the system from authenticating. "
            "Contact support."
        ),
        retryable=False,
        details_template="",
    ),

    ErrorCode.VERTEX_ABORTED: ErrorInfo(
        code="VERTEX_ABORTED",
        http_status=503,
        message=(
            "The Vertex AI operation was aborted, typically due to a concurrency conflict "
            "(google.api_core.exceptions.Aborted)."
        ),
        user_hint=(
            "The request was interrupted. Please try again."
        ),
        retryable=True,
        details_template="",
    ),

    # ------------------------------------------------------------------
    # Pipeline / Processing Errors
    # ------------------------------------------------------------------

    ErrorCode.FILE_PARSE_FAILED: ErrorInfo(
        code="FILE_PARSE_FAILED",
        http_status=422,
        message=(
            "Failed to extract text from the uploaded file. "
            "The file may be corrupt, password-protected, or in an unsupported encoding."
        ),
        user_hint=(
            "Your file could not be read. Make sure it is not password-protected or corrupted "
            "and try uploading it again."
        ),
        retryable=False,
        details_template="",
    ),

    # Merged from both sources; richer ErrorInfo from backend/error_codes.py kept.
    ErrorCode.UNSUPPORTED_FILE_TYPE: ErrorInfo(
        code="UNSUPPORTED_FILE_TYPE",
        http_status=415,
        message=(
            "The uploaded file's extension or MIME type is not supported by the pipeline. "
            "Accepted formats: PDF, TXT, DOCX, HTML."
        ),
        user_hint=(
            "The file type you uploaded is not supported. "
            "Please upload a PDF, TXT, DOCX, or HTML file."
        ),
        retryable=False,
        details_template="File must be PDF, TXT, DOCX, or HTML; got {ext}",
    ),

    ErrorCode.EMPTY_DOCUMENT: ErrorInfo(
        code="EMPTY_DOCUMENT",
        http_status=422,
        message=(
            "The document produced no extractable text after parsing. "
            "It may be a scanned image without OCR, an empty file, or all-whitespace content."
        ),
        user_hint=(
            "No readable text was found in the document. "
            "Make sure the file contains selectable text (not just a scanned image) and try again."
        ),
        retryable=False,
        details_template="",
    ),

    ErrorCode.JOB_TIMEOUT: ErrorInfo(
        code="JOB_TIMEOUT",
        http_status=504,
        message=(
            "The job exceeded its allocated processing time "
            "before all pipeline stages could complete."
        ),
        user_hint=(
            "Processing took too long and was stopped. "
            "Try uploading a shorter document."
        ),
        retryable=False,
        details_template="Job exceeded the worker time limit at stage {stage}",
    ),

    ErrorCode.PIPELINE_VALIDATION_FAILED: ErrorInfo(
        code="PIPELINE_VALIDATION_FAILED",
        http_status=500,
        message=(
            "Pydantic validation of the LLM-structured output failed. "
            "The model response did not conform to the expected output schema."
        ),
        user_hint=(
            "An internal error occurred while validating the AI output. Please try again."
        ),
        retryable=True,
        details_template="",
    ),

    ErrorCode.PIPELINE_ERROR: ErrorInfo(
        code="PIPELINE_ERROR",
        http_status=500,
        message="Pipeline error",
        user_hint="Pipeline error",
        retryable=True,
        details_template="Unexpected error during processing: {detail}",
    ),

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    ErrorCode.UNAUTHORIZED: ErrorInfo(
        code="UNAUTHORIZED",
        http_status=401,
        message="Authentication failed",
        user_hint="Authentication failed",
        retryable=False,
        details_template="Invalid or expired token: {detail}",
    ),

    ErrorCode.MISSING_AUTH_HEADER: ErrorInfo(
        code="MISSING_AUTH_HEADER",
        http_status=401,
        message="No authorization header",
        user_hint="No authorization header",
        retryable=False,
        details_template="Request must include an Authorization: Bearer <token> header",
    ),

    ErrorCode.MALFORMED_AUTH_HEADER: ErrorInfo(
        code="MALFORMED_AUTH_HEADER",
        http_status=400,
        message="Malformed Authorization header",
        user_hint="Malformed Authorization header",
        retryable=False,
        details_template="Expected format: Authorization: Bearer <token>",
    ),

    ErrorCode.ANONYMOUS_ACCESS_FORBIDDEN: ErrorInfo(
        code="ANONYMOUS_ACCESS_FORBIDDEN",
        http_status=403,
        message="Anonymous access denied",
        user_hint="Please sign in with an account to use this feature",
        retryable=False,
        details_template="This endpoint does not accept anonymous Firebase tokens",
    ),

    # ------------------------------------------------------------------
    # Resource
    # ------------------------------------------------------------------

    ErrorCode.RESOURCE_NOT_FOUND: ErrorInfo(
        code="RESOURCE_NOT_FOUND",
        http_status=404,
        message="Resource not found",
        user_hint="Resource not found",
        retryable=False,
        details_template="{collection} document {doc_id} does not exist",
    ),

    ErrorCode.RESOURCE_FORBIDDEN: ErrorInfo(
        code="RESOURCE_FORBIDDEN",
        http_status=403,
        message="Access denied",
        user_hint="Access denied",
        retryable=False,
        details_template="You do not own {collection} document {doc_id}",
    ),

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------

    ErrorCode.INPUT_VALIDATION_ERROR: ErrorInfo(
        code="INPUT_VALIDATION_ERROR",
        http_status=422,
        message="Invalid request input",
        user_hint="Invalid request input",
        retryable=False,
        details_template="{field}: {reason}",
    ),

    ErrorCode.FILE_TOO_LARGE: ErrorInfo(
        code="FILE_TOO_LARGE",
        http_status=413,
        message="File exceeds size limit",
        user_hint="File exceeds size limit",
        retryable=False,
        details_template="File size {size_mb}MB exceeds {limit_mb}MB limit",
    ),

    # ------------------------------------------------------------------
    # Timeout
    # ------------------------------------------------------------------

    ErrorCode.TIMEOUT: ErrorInfo(
        code="TIMEOUT",
        http_status=504,
        message="Request timed out",
        user_hint="Request timed out",
        retryable=True,
        details_template="Operation exceeded time limit",
    ),

    # ------------------------------------------------------------------
    # System / Catch-all
    # ------------------------------------------------------------------

    # UNKNOWN_ERROR: _classify_exc fallback for unclassified pipeline exceptions
    ErrorCode.UNKNOWN_ERROR: ErrorInfo(
        code="UNKNOWN_ERROR",
        http_status=500,
        message=(
            "An unexpected error occurred that does not match any known error class. "
            "See server logs for full traceback."
        ),
        user_hint=(
            "An unexpected error occurred. Please try again. "
            "If the problem persists, contact support."
        ),
        retryable=False,
        details_template="",
    ),

    # INTERNAL_ERROR: HTTP routes and Flask global error handlers
    ErrorCode.INTERNAL_ERROR: ErrorInfo(
        code="INTERNAL_ERROR",
        http_status=500,
        message="Internal server error",
        user_hint="Internal server error",
        retryable=False,
        details_template="An unexpected error occurred",
    ),

    ErrorCode.ENDPOINT_NOT_FOUND: ErrorInfo(
        code="ENDPOINT_NOT_FOUND",
        http_status=404,
        message="Endpoint not found",
        user_hint="Endpoint not found",
        retryable=False,
        details_template="No route matches {method} {path}",
    ),

    ErrorCode.RATE_LIMIT_EXCEEDED: ErrorInfo(
        code="RATE_LIMIT_EXCEEDED",
        http_status=429,
        message="Rate limit exceeded",
        user_hint="You've reached the limit of 5 simplifications per hour. Please try again later.",
        retryable=True,
    ),
}


# ---------------------------------------------------------------------------
# Completeness assertion: every ErrorCode must have a catalog entry
# ---------------------------------------------------------------------------

_missing = [ec for ec in ErrorCode if ec not in ERROR_CATALOG]
if _missing:
    raise AssertionError(
        f"errors/codes.py: missing ERROR_CATALOG entries for: {[ec.value for ec in _missing]}"
    )
