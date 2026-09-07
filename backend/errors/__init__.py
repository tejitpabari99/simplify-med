"""errors — unified error package for the Simplify backend.

Import from here; do not import directly from errors.codes or errors.exceptions
unless you need an internal symbol not re-exported here.
"""
from errors.codes import ERROR_CATALOG, ErrorCode, ErrorInfo
from errors.exceptions import (
    SimplifyError,
    make_error_response,
    build_error_data,
    build_error_data_from_exc,
    handle_exception,
    classify_finish_reason,
)
from errors.vertex_errors import VertexAPIError

__all__ = [
    "ERROR_CATALOG", "ErrorCode", "ErrorInfo",
    "SimplifyError",
    "make_error_response",
    "build_error_data",
    "build_error_data_from_exc",
    "handle_exception",
    "classify_finish_reason",
    "VertexAPIError",
]
