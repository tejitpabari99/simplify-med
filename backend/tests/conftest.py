import sys
from pathlib import Path
import json
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent

# Ensure BACKEND_DIR is at position 0 so it shadows tests/routes, tests/models,
# tests/utils when doing `from routes import ...` etc.  Simply checking
# `if str(p) not in sys.path` is insufficient — pytest may have already added
# BACKEND_DIR at a position *after* tests/, so we forcibly move it to the front.
for p in (str(BACKEND_DIR), str(PROJECT_DIR)):
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)

from flask import Flask
from routes import API_BLUEPRINTS


@pytest.fixture
def app():
    app = Flask(__name__)
    for bp in API_BLUEPRINTS:
        app.register_blueprint(bp)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_ok(monkeypatch):
    """Bypass Firebase auth: any Bearer token resolves to a fixed uid."""
    monkeypatch.setattr("utils.firebase.auth.verify_id_token", lambda *a, **k: {"uid": "user-1"})
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def fake_firestore(monkeypatch):
    """Patch firestore.client() to a MagicMock; return it for per-test wiring."""
    from unittest.mock import MagicMock
    db = MagicMock()
    monkeypatch.setattr("firebase_admin.firestore.client", lambda *a, **k: db)
    return db


def parse_sse(response):
    """Split an SSE response body into a list of parsed JSON event payloads."""
    text = response.get_data(as_text=True) if hasattr(response, "get_data") else response
    events = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        if block.startswith("data: "):
            events.append(json.loads(block.removeprefix("data: ")))
    return events
