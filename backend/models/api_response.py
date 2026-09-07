"""Pydantic models for the API error contract wire shape."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from .base import JsonModel


class StatusEnum(str, Enum):
    error       = "error"
    success     = "success"
    not_started = "not_started"
    processing  = "processing"
    completed   = "completed"


class ErrorDetail(JsonModel):
    """Structured error payload.

    Intentionally usable without an HTTP request context:
    - `path` is Optional (workers writing Firestore job docs have no path).
    - `timestamp` is an ISO-8601 UTC string; callers use datetime.now(timezone.utc).isoformat().
    - `code` is always a string (ErrorCode.value), not the enum, so it is JSON-serializable
      without extra config and safe to store in Firestore.

    User-facing fields (safe to display in client UI):
        code: Public error code string (ErrorCode.value).
        message: Short developer/user-facing error message.
        user_hint: Optional guidance for the end user on how to resolve the error.
        retryable: Whether the client should retry the request.

    Internal fields (suitable for logs and support diagnostics; may be omitted from client UI):
        details: Additional internal context string (stack info, upstream error text, etc.).
        timestamp: ISO-8601 UTC timestamp of when the error was generated.
        path: Request path where the error occurred (None for non-HTTP contexts such as workers).
    """
    code: str
    message: str
    details: Optional[str] = None
    timestamp: str
    path: str | None = None
    user_hint: Optional[str] = None
    retryable: bool = False


class ApiResponse(JsonModel):
    """Top-level envelope for every HTTP response.

    Success:  ApiResponse(status="success", data={...})
    Error:    ApiResponse(status="error", error=ErrorDetail(...))
    The HTTP status code lives on the HTTP layer, not duplicated here.
    """
    status: StatusEnum
    data: dict[str, Any] | None = None
    error: ErrorDetail | None = None
    requestId: str | None = None
