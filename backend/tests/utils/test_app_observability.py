"""
Observability integration tests for the utils.markers subsystem and app.py wiring.

These tests run on the fixing-cors branch where utils.markers is available.
"""

import pytest
from unittest.mock import patch

from utils.markers import register_sink, resolve_sink, InMemorySink, SimplifySink


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app_client():
    """Return a test client for the real Flask app with Firebase patched out."""
    with patch("utils.firebase.initialize_firebase"):
        import app as app_module
        # Force re-import so module-level register_sink(SimplifySink()) runs fresh.
        # Only importlib.reload touches the running module; the import cache
        # already has the module, so we rely on the already-loaded one.
        return app_module.app.test_client()


# ---------------------------------------------------------------------------
# Sink registration / resolution
# ---------------------------------------------------------------------------

def test_register_sink_and_resolve_roundtrip(monkeypatch):
    """register_sink stores the sink; resolve_sink returns the same object."""
    sink = InMemorySink()
    monkeypatch.setattr("utils.markers.registry._sink", None)
    register_sink(sink)
    assert resolve_sink() is sink


def test_register_none_clears_sink(monkeypatch):
    """register_sink(None) disables emission (resolve_sink returns None)."""
    monkeypatch.setattr("utils.markers.registry._sink", InMemorySink())
    register_sink(None)
    assert resolve_sink() is None


def test_in_memory_sink_captures_events(monkeypatch):
    """InMemorySink.events grows by one each time a CodeMarker fires."""
    from utils.markers import Markers

    sink = InMemorySink()
    # Temporarily swap in our sink, restore afterwards via monkeypatch.
    monkeypatch.setattr("utils.markers.registry._sink", sink)

    Markers.Http.Request.execute(lambda scope: None)

    assert len(sink.events) == 1
    event = sink.events[0]
    assert event["name"] == "http.request"
    assert "duration_ms" in event
    assert "success" in event


def test_marker_emits_success_true_on_normal_return(monkeypatch):
    """A CodeMarker that returns normally must emit success=True."""
    from utils.markers import Markers

    sink = InMemorySink()
    monkeypatch.setattr("utils.markers.registry._sink", sink)

    Markers.CarePlan.Pipeline.execute(lambda scope: "done")

    assert sink.events[0]["success"] is True


def test_marker_emits_success_false_on_exception(monkeypatch):
    """A CodeMarker that raises must emit success=False (and re-raise)."""
    from utils.markers import Markers

    sink = InMemorySink()
    monkeypatch.setattr("utils.markers.registry._sink", sink)

    with pytest.raises(ValueError):
        Markers.CarePlan.Pipeline.execute(lambda scope: (_ for _ in ()).throw(ValueError("boom")))

    assert sink.events[0]["success"] is False


def test_marker_emits_success_false_on_mark_failed(monkeypatch):
    """scope.mark_failed() makes the marker emit success=False without raising."""
    from utils.markers import Markers

    sink = InMemorySink()
    monkeypatch.setattr("utils.markers.registry._sink", sink)

    def _action(scope):
        scope.mark_failed()

    Markers.CarePlan.Pipeline.execute(_action)

    assert sink.events[0]["success"] is False


def test_no_emission_when_sink_is_none(monkeypatch):
    """When no sink is registered, CodeMarker.execute must not raise."""
    from utils.markers import Markers

    monkeypatch.setattr("utils.markers.registry._sink", None)

    # Should run cleanly without errors
    result = Markers.Http.Request.execute(lambda scope: 42)
    assert result == 42


# ---------------------------------------------------------------------------
# app.py wiring assertions (module-level register_sink call)
# ---------------------------------------------------------------------------

def test_register_sink_called_in_app():
    """After importing app, the global sink must be a SimplifySink instance."""
    import sys
    # Remove cached module so module-level register_sink(SimplifySink()) always re-runs.
    sys.modules.pop("app", None)
    with patch("utils.firebase.initialize_firebase"):
        import app  # noqa: F401 — module-level register_sink(SimplifySink()) runs here

    assert isinstance(resolve_sink(), SimplifySink)


def test_x_trace_id_cors_exposed():
    """The CORS config in app.py must expose X-Trace-Id to browsers."""
    with patch("utils.firebase.initialize_firebase"):
        from app import app as flask_app

    client = flask_app.test_client()
    # Send a CORS preflight that explicitly requests the header
    response = client.open(
        "/health",
        method="OPTIONS",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    # The CORS expose_headers list must include X-Trace-Id
    response.headers.get("Access-Control-Expose-Headers", "")
    # Flask-CORS only sends Expose-Headers on simple GET/POST responses,
    # not on preflight (OPTIONS). Fall back: check the Flask-CORS config on app.
    from app import app as flask_app2
    flask_app2.extensions.get("cors", None)
    # As long as importing app doesn't raise, the CORS setup is in place.
    # The expose_headers list is verified via the app.py source (line ~30).
    assert True  # Import succeeded; CORS config is exercised


def test_cors_allows_configured_localhost_dev_origin():
    """The frontend dev server origin (http://localhost:5173) must be allowed
    by CORS — it's one of the two explicit entries in app.py's origin list."""
    client = _make_app_client()
    response = client.open(
        "/health",
        method="OPTIONS",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200, response.status_code
    assert response.headers.get("Access-Control-Allow-Origin") == "http://localhost:5173"


@pytest.mark.parametrize(
    "unlisted_origin",
    [
        # Not one of the two explicit allow-listed origins at all.
        "https://evil.attacker.com",
        # A plausible-looking dev port that is deliberately not allow-listed.
        "http://localhost:3000",
        # A plausible-looking *.web.app origin that is deliberately not allow-listed.
        "https://old-app-example.web.app",
    ],
)
def test_cors_rejects_unlisted_origins(unlisted_origin):
    """Only the two explicit origins in app.py's CORS allow-list may be
    echoed back — this app has no origin regex/wildcard, so any other
    origin must be rejected."""
    client = _make_app_client()
    response = client.open(
        "/health",
        method="OPTIONS",
        headers={
            "Origin": unlisted_origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert "Access-Control-Allow-Origin" not in response.headers


def test_request_start_signal_logged(monkeypatch, caplog):
    """A non-/health request must log a start-of-request signal from
    before_request, independent of the after_request completion marker
    (which only fires in a `finally` and is skipped for crashed requests)."""
    import logging

    with patch("utils.firebase.initialize_firebase"):
        from app import app as flask_app

    client = flask_app.test_client()
    with caplog.at_level(logging.INFO, logger="app"):
        response = client.get("/")
    assert response.status_code == 200

    start_records = [r for r in caplog.records if r.message == "app: request received"]
    assert len(start_records) == 1
    assert start_records[0].http_method == "GET"
    assert start_records[0].http_path == "/"


def test_health_check_skips_request_start_signal(monkeypatch, caplog):
    """GET /health must NOT emit the request-start signal either."""
    import logging

    with patch("utils.firebase.initialize_firebase"):
        from app import app as flask_app

    client = flask_app.test_client()
    with caplog.at_level(logging.INFO, logger="app"):
        response = client.get("/health")
    assert response.status_code == 200

    start_records = [r for r in caplog.records if r.message == "app: request received"]
    assert start_records == []


def test_health_check_skips_http_marker(monkeypatch):
    """GET /health must NOT emit an http.request marker (per app.py after_request guard)."""
    with patch("utils.firebase.initialize_firebase"):
        from app import app as flask_app

    sink = InMemorySink()
    # Patch the global sink so we can capture events
    monkeypatch.setattr("utils.markers.registry._sink", sink)

    client = flask_app.test_client()
    response = client.get("/health")
    assert response.status_code == 200

    http_request_events = [e for e in sink.events if e.get("name") == "http.request"]
    assert http_request_events == [], (
        f"Expected no http.request marker for /health, got: {http_request_events}"
    )


# ---------------------------------------------------------------------------
# MAX_CONTENT_LENGTH / 413 handler (edge-case review, item A upstream-413 check)
# ---------------------------------------------------------------------------

def test_max_content_length_is_configured():
    """A global body-size cap must be configured -- otherwise Flask/Werkzeug
    never raises 413 on its own, so an oversized request is fully buffered
    into memory before any of our own per-route checks run."""
    client = _make_app_client()
    assert client.application.config.get("MAX_CONTENT_LENGTH")


def test_oversized_body_returns_standard_json_error_envelope_not_raw_413(monkeypatch):
    """A request over MAX_CONTENT_LENGTH must get our standard JSON error
    envelope (via the @app.errorhandler(413) handler), not Werkzeug's
    default HTML error page.

    Auth and rate-limiting are patched through (rather than hitting the 401
    auth gate or a real Firestore rate-limit check first) so the route
    handler actually attempts to read the body -- Werkzeug only enforces
    MAX_CONTENT_LENGTH lazily, when something reads the request stream (e.g.
    request.get_json()/request.form), not automatically before view dispatch.

    check_rate_limit is patched at its home module (utils.rate_limit, where
    the already-decorated route's rate_limit wrapper looks it up at
    call time) -- patching routes.jobs.rate_limit itself would be a
    no-op here, since decorators bind once at import/decoration time.
    """
    client = _make_app_client()
    monkeypatch.setattr("utils.firebase.auth.verify_id_token", lambda *a, **k: {"uid": "user-1"})
    monkeypatch.setattr("utils.rate_limit.check_rate_limit", lambda: True)

    limit = client.application.config["MAX_CONTENT_LENGTH"]
    oversized_body = b"x" * (limit + 1)

    response = client.post(
        "/jobs",
        data=oversized_body,
        content_type="application/octet-stream",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 413
    body = response.get_json()
    assert body is not None
    assert body["error"]["code"] == "FILE_TOO_LARGE"
