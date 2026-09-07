"""Tests for the /health endpoint defined in app.py."""
from unittest.mock import patch


def test_health_returns_200():
    """Import the real app (patching Firebase init) and confirm /health is 200."""
    with patch("utils.firebase.initialize_firebase"):
        from app import app as flask_app
    client = flask_app.test_client()
    response = client.get("/health")
    assert response.status_code == 200


def test_health_returns_json():
    """Response body must be parseable JSON."""
    with patch("utils.firebase.initialize_firebase"):
        from app import app as flask_app
    client = flask_app.test_client()
    response = client.get("/health")
    data = response.get_json()
    assert data is not None
    assert isinstance(data, dict)


def test_health_status_is_healthy():
    """Response JSON must have status == 'healthy'."""
    with patch("utils.firebase.initialize_firebase"):
        from app import app as flask_app
    client = flask_app.test_client()
    response = client.get("/health")
    data = response.get_json()
    assert data["status"] == "healthy"


def test_health_message_present():
    """Response JSON must include a 'message' field."""
    with patch("utils.firebase.initialize_firebase"):
        from app import app as flask_app
    client = flask_app.test_client()
    response = client.get("/health")
    data = response.get_json()
    assert "message" in data
