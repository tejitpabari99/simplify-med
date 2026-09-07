import logging
import uuid
import os

from flask import Flask, jsonify, request, g
from flask_cors import CORS
from opentelemetry import trace

import os as _os
from routes import API_BLUEPRINTS, WORKER_BLUEPRINTS
from errors import make_error_response, ErrorCode
from utils.firebase import initialize_firebase
from observability import setup_logging, init_telemetry
from utils.misc import monotonic_ms

# ---------------------------------------------------------------------------
# Bootstrap logging FIRST so all subsequent log calls use structured output
# ---------------------------------------------------------------------------
setup_logging()
from utils.markers import register_sink, SimplifySink, Markers, SimplifyContext
register_sink(SimplifySink())
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Initialize Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)

# Resource-safety net: rejects a wildly oversized body before Flask buffers it
# into memory, ahead of our own per-route checks. Sized above the largest
# legitimate request (Constants.Limits.MAX_AGGREGATE_FILE_BYTES = 10 MB, plus
# multipart overhead) and below Cloud Run's own ~32 MiB request ceiling. Not
# the primary enforcement -- routes/jobs.py / services/care_plan_input.py's
# 10 MB aggregate check is the real, user-facing limit and runs first.
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024

# Enable CORS for all routes with explicit origin/header/method allow-lists
CORS(
    app,
    origins=[
        "https://your-production-domain.example",  # placeholder — replace with your deployed frontend origin
        "http://localhost:5173",                    # frontend dev server
    ],
    methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Session-Id"],
    expose_headers=["X-Session-Id", "X-Trace-Id"],
    supports_credentials=False,
    max_age=600,
)

# ---------------------------------------------------------------------------
# Initialize OpenTelemetry (instruments Flask + outgoing HTTP)
# ---------------------------------------------------------------------------
init_telemetry(app)

# ---------------------------------------------------------------------------
# Initialize Firebase
# ---------------------------------------------------------------------------
initialize_firebase()

# ---------------------------------------------------------------------------
# Register all route blueprints
# ---------------------------------------------------------------------------
SERVICE_MODE = _os.environ.get("SERVICE_MODE", "api")
if SERVICE_MODE == "worker":
    _blueprints = WORKER_BLUEPRINTS
elif SERVICE_MODE == "combined":
    # Combined mode (used by ephemeral PR previews): a single service serves
    # both the API routes (which enqueue Cloud Tasks) and the worker routes
    # (which execute them), enqueuing tasks that call back into itself.
    # Dedupe in case any blueprint is shared between the two lists.
    _seen: set = set()
    _blueprints = []
    for bp in (*API_BLUEPRINTS, *WORKER_BLUEPRINTS):
        if id(bp) not in _seen:
            _seen.add(id(bp))
            _blueprints.append(bp)
else:
    _blueprints = API_BLUEPRINTS
for bp in _blueprints:
    app.register_blueprint(bp)


# ---------------------------------------------------------------------------
# Session ID middleware
# ---------------------------------------------------------------------------

@app.before_request
def extract_session_id():
    """
    Determine the session_id for this request and store it on flask.g
    for use in route handlers, structured logging, and Cloud Trace.

    Source: X-Session-Id request header, or a generated UUID if absent.
    Never falls back to user_id -- keeps session tracking independent of auth identity.
    """
    session_id = request.headers.get("X-Session-Id", "") or str(uuid.uuid4())
    g.session_id = session_id
    g.request_start_ms = monotonic_ms()

    current_span = trace.get_current_span()
    if current_span and current_span.is_recording():
        current_span.set_attribute("session.id", session_id)
        current_span.set_attribute("http.route", request.path)

    # Emit a start-of-request signal immediately (not deferred to
    # after_request's `finally`) so there's log evidence a request was
    # received even if the process crashes/OOMs/hard-times-out before the
    # response completes. Skip /health to avoid health-check log spam,
    # mirroring the after_request marker's gating.
    if request.path != "/health":
        logger.info(
            "app: request received",
            extra={"http_method": request.method, "http_path": request.path},
        )


@app.after_request
def attach_session_id_header(response):
    """Echo the session ID back to the client and emit the request-lifecycle marker."""
    session_id = getattr(g, "session_id", None)
    if session_id:
        response.headers["X-Session-Id"] = session_id

    span_ctx = trace.get_current_span().get_span_context()
    if span_ctx and span_ctx.is_valid:
        response.headers["X-Trace-Id"] = format(span_ctx.trace_id, "032x")

    # Record request-level metrics + timeline log via Markers (skip health checks
    # and SSE routes — the latter emit their own per-chunk markers).
    if request.path != "/health" and response.content_type != "text/event-stream":
        start_ms = getattr(g, "request_start_ms", None)
        duration_ms = (monotonic_ms() - start_ms) if start_ms is not None else 0.0

        def _emit(scope):
            SimplifyContext.from_g(function="http_request").apply(scope)
            scope.add("http_method", request.method)
            scope.add("http_path", request.path)
            scope.add("http_status", str(response.status_code))
            scope.add("duration_ms_observed", round(duration_ms, 1))
            if response.status_code >= 500:
                scope.mark_failed()
        Markers.Http.Request.execute(_emit)

    return response


# ---------------------------------------------------------------------------
# Health check endpoint
# ---------------------------------------------------------------------------

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint to verify API is running"""
    return jsonify({
        'status': 'healthy',
        'message': 'Medical Scribe Processing API is running'
    }), 200


# ---------------------------------------------------------------------------
# Root endpoint
# ---------------------------------------------------------------------------

@app.route('/', methods=['GET'])
def root():
    """Root endpoint with API information"""
    return jsonify({
        'name': 'Medical Scribe Processing API',
        'version': '1.1.0',
        'endpoints': {
            'POST /jobs': 'Create an async care-plan job',
            'DELETE /jobs/<job_id>': 'Delete a completed or failed job',
            'GET /health': 'Health check',
        }
    }), 200


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(error):
    return make_error_response(
        ErrorCode.ENDPOINT_NOT_FOUND,
        request.path,
        {"method": request.method, "path": request.path},
    ).to_dict(), 404

@app.errorhandler(405)
def method_not_allowed(error):
    return make_error_response(
        ErrorCode.ENDPOINT_NOT_FOUND,
        request.path,
        {"method": request.method, "path": request.path},
    ).to_dict(), 405

@app.errorhandler(500)
def internal_error(error):
    return make_error_response(
        ErrorCode.INTERNAL_ERROR,
        request.path,
    ).to_dict(), 500

@app.errorhandler(413)
def request_entity_too_large(error):
    # Reached only if Werkzeug itself rejects an oversized body against
    # MAX_CONTENT_LENGTH above, before any route handler runs -- without this
    # handler, that would be Werkzeug's default HTML error page rather than
    # our standard JSON error envelope (edge-case review, item A's upstream-413
    # check).
    limit_mb = (app.config.get("MAX_CONTENT_LENGTH") or 0) // (1024 * 1024)
    return make_error_response(
        ErrorCode.FILE_TOO_LARGE,
        request.path,
        {"size_mb": f">{limit_mb}", "limit_mb": limit_mb},
    ).to_dict(), 413


# ---------------------------------------------------------------------------
# Dev server entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(
        host='0.0.0.0',
        port=port,
        debug=os.environ.get('FLASK_ENV') == 'development'
    )
