"""
OpenTelemetry setup for Google Cloud Trace integration.

Initializes:
- TracerProvider with GCP Cloud Trace exporter (production) or console exporter (dev)
- Flask auto-instrumentation (creates a span per HTTP request)
- Requests library auto-instrumentation (traces outgoing HTTP calls)

Usage:
    from telemetry import init_telemetry, get_tracer
    init_telemetry(app)  # call once at startup
    tracer = get_tracer()
"""

import os
import logging

from opentelemetry import trace

from utils.constants import Constants
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor

logger = logging.getLogger(__name__)


def _build_version() -> str:
    """Read baked version constant from the VERSION file in the backend root."""
    try:
        import pathlib
        version_file = pathlib.Path(__file__).parent.parent / "VERSION"
        return version_file.read_text().strip()
    except Exception:
        return "unknown"


SERVICE_VERSION = os.environ.get("SERVICE_VERSION") or _build_version()

_initialized = False


def init_telemetry(flask_app):
    """
    Initialize OpenTelemetry tracing and instrument the Flask app.

    In production (on Cloud Run / GCP), traces are exported to Cloud Trace.
    In development, traces are printed to the console.

    Must be called once at application startup, before any requests are served.
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    gcp_project_id = os.getenv("GCP_PROJECT_ID", "")
    is_production = os.getenv("K_SERVICE") is not None  # K_SERVICE is set on Cloud Run

    # Resource identifies this service in Cloud Trace.
    # SERVICE_VERSION should be set to the git SHA or semver on each deploy so
    # version-segmented latency comparisons in Cloud Trace work correctly.
    resource = Resource.create({
        "service.name": os.getenv(Constants.EnvVars.K_SERVICE, Constants.Observability.SERVICE_NAME_DEFAULT),
        "service.version": SERVICE_VERSION,
    })

    provider = TracerProvider(resource=resource)

    if is_production and gcp_project_id:
        try:
            from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

            cloud_trace_exporter = CloudTraceSpanExporter(project_id=gcp_project_id)
            provider.add_span_processor(BatchSpanProcessor(cloud_trace_exporter))
            logger.info("OpenTelemetry: Cloud Trace exporter configured (project=%s)", gcp_project_id)
        except Exception as e:
            logger.warning("OpenTelemetry: Failed to initialize Cloud Trace exporter: %s. Falling back to console.", e)
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    else:
        # Development: print spans to console
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        logger.info("OpenTelemetry: Console exporter configured (dev mode)")

    trace.set_tracer_provider(provider)

    # Auto-instrument Flask — creates a span for every incoming HTTP request
    FlaskInstrumentor().instrument_app(flask_app)

    # Auto-instrument the `requests` library — traces outgoing HTTP calls
    RequestsInstrumentor().instrument()

    logger.info("OpenTelemetry: Initialization complete")


def get_tracer(name: str = Constants.Observability.SERVICE_NAME_DEFAULT):
    """Return an OpenTelemetry tracer for manual span creation."""
    return trace.get_tracer(name)
