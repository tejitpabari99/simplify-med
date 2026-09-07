"""errors/vertex_errors.py — Vertex AI / Google API error type and classification."""
from __future__ import annotations

from errors.codes import ErrorCode
from errors.exceptions import SimplifyError


class VertexAPIError(SimplifyError):
    """Raised when a Vertex AI google.api_core call fails.

    Wraps the raw google.api_core exception and classifies it into a
    SimplifyError ErrorCode via VertexAPIError.classify(). Callers that need to
    handle Vertex AI failures uniformly catch VertexAPIError (or SimplifyError)
    instead of reaching into google.api_core.exceptions directly.
    """

    def __init__(self, original: Exception, detail: str | None = None) -> None:
        code = self.classify(original)
        super().__init__(code, detail=detail or str(original), original=original)

    @classmethod
    def classify(cls, exc: Exception) -> ErrorCode:
        """Map a google.api_core.exceptions.* instance to the matching ErrorCode.

        Returns ErrorCode.UNKNOWN_ERROR if google-api-core is not installed
        or the exception type is not in the mapping below.
        """
        try:
            from google.api_core import exceptions as _gexc
        except ImportError:
            return ErrorCode.UNKNOWN_ERROR

        _TYPE_MAP = [
            (_gexc.ResourceExhausted,   ErrorCode.VERTEX_QUOTA_EXCEEDED),
            (_gexc.DeadlineExceeded,    ErrorCode.VERTEX_DEADLINE_EXCEEDED),
            (_gexc.InvalidArgument,     ErrorCode.VERTEX_INVALID_ARGUMENT),
            (_gexc.PermissionDenied,    ErrorCode.VERTEX_PERMISSION_DENIED),
            (_gexc.NotFound,            ErrorCode.VERTEX_NOT_FOUND),
            (_gexc.ServiceUnavailable,  ErrorCode.VERTEX_SERVICE_UNAVAILABLE),
            (_gexc.InternalServerError, ErrorCode.VERTEX_INTERNAL_ERROR),
            (_gexc.Unauthenticated,     ErrorCode.VERTEX_UNAUTHENTICATED),
            (_gexc.Aborted,             ErrorCode.VERTEX_ABORTED),
        ]
        for exc_type, code in _TYPE_MAP:
            if isinstance(exc, exc_type):
                return code
        return ErrorCode.UNKNOWN_ERROR
