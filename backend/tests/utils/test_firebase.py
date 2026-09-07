"""Tests for utils/firebase.py — TDD: write tests first, then create the module."""

import pytest
from unittest.mock import MagicMock, patch

from flask import Flask


# ---------------------------------------------------------------------------
# initialize_firebase
# ---------------------------------------------------------------------------

@patch("utils.firebase.firebase_admin._apps", {"app": MagicMock()})
@patch("utils.firebase.firebase_admin.initialize_app")
@patch("utils.firebase.firestore.client")
def test_does_not_reinit_when_already_initialized(mock_client, mock_init_app):
    from utils.firebase import initialize_firebase

    initialize_firebase()
    mock_init_app.assert_not_called()


@patch("utils.firebase.firebase_admin._apps", {})
@patch.dict("os.environ", {"FIREBASE_SERVICE_ACCOUNT_JSON": '{"type": "service_account"}'})
@patch("utils.firebase.credentials.Certificate")
@patch("utils.firebase.firebase_admin.initialize_app")
@patch("utils.firebase.firestore.client")
def test_inits_with_json_env_when_not_initialized(mock_client, mock_init_app, mock_cert):
    from utils.firebase import initialize_firebase

    initialize_firebase()
    mock_cert.assert_called_once_with({"type": "service_account"})
    mock_init_app.assert_called_once()


@patch("utils.firebase.firebase_admin._apps", {})
@patch.dict("os.environ", {}, clear=False)
@patch("utils.firebase.firebase_admin.initialize_app")
@patch("utils.firebase.firestore.client")
def test_inits_with_default_credentials_when_no_env(mock_client, mock_init_app):
    import os
    # Ensure neither JSON nor path env var is set
    env_backup = {}
    for key in ("FIREBASE_SERVICE_ACCOUNT_JSON", "FIREBASE_SERVICE_ACCOUNT_PATH"):
        if key in os.environ:
            env_backup[key] = os.environ.pop(key)
    try:
        from utils.firebase import initialize_firebase
        initialize_firebase()
        mock_init_app.assert_called_once_with()
    finally:
        os.environ.update(env_backup)


@patch("utils.firebase.firebase_admin._apps", {"app": MagicMock()})
@patch("utils.firebase.firestore.client")
def test_returns_firestore_client(mock_client):
    from utils.firebase import initialize_firebase

    mock_client.return_value = MagicMock()
    result = initialize_firebase()
    mock_client.assert_called_once()
    assert result == mock_client.return_value


# ---------------------------------------------------------------------------
# firestore_client
# ---------------------------------------------------------------------------

@patch("utils.firebase.firestore.client")
def test_uses_default_database_id(mock_client):
    import os
    os.environ.pop("FIRESTORE_DATABASE_ID", None)
    from utils.firebase import firestore_client

    firestore_client()
    mock_client.assert_called_once_with(database_id="(default)")


@patch.dict("os.environ", {"FIRESTORE_DATABASE_ID": "my-db"})
@patch("utils.firebase.firestore.client")
def test_uses_env_database_id(mock_client):
    from utils.firebase import firestore_client

    firestore_client()
    mock_client.assert_called_once_with(database_id="my-db")


@patch("utils.firebase.firestore.client")
def test_returns_firestore_client_instance(mock_client):
    from utils.firebase import firestore_client

    fake_db = MagicMock()
    mock_client.return_value = fake_db
    result = firestore_client()
    assert result is fake_db


# ── _extract_bearer_token ──────────────────────────────────────────────────────

def test_extract_bearer_token_missing_header():
    from utils.firebase import _extract_bearer_token
    token, err = _extract_bearer_token(None)
    assert token is None
    assert err is not None
    assert err[1] == 401


def test_extract_bearer_token_malformed():
    from utils.firebase import _extract_bearer_token
    token, err = _extract_bearer_token("Token abc")
    assert token is None
    assert err is not None
    assert err[1] == 401


def test_extract_bearer_token_valid():
    from utils.firebase import _extract_bearer_token
    token, err = _extract_bearer_token("Bearer mytoken")
    assert token == "mytoken"
    assert err is None


# ── FirestoreError job-lifecycle wrappers ──────────────────────────────────────

@patch("utils.firebase.firestore_client")
def test_create_job_doc_raises_firestore_error_on_exception(mock_client):
    from utils.firebase import create_job_doc, FirestoreError
    mock_client.return_value.collection.return_value.document.return_value.set.side_effect = Exception("network")
    with pytest.raises(FirestoreError) as exc_info:
        create_job_doc(user_id="u1", job_id="j1", payload={})
    assert "create_job_doc failed" in str(exc_info.value)


@patch("utils.firebase.firestore_client")
def test_update_job_stage_raises_firestore_error(mock_client):
    from utils.firebase import update_job_stage, FirestoreError
    mock_client.return_value.collection.return_value.document.return_value.update.side_effect = Exception("network")
    with pytest.raises(FirestoreError):
        update_job_stage("j1", 2)


@patch("utils.firebase.firestore_client")
def test_complete_job_raises_firestore_error(mock_client):
    from utils.firebase import complete_job, FirestoreError
    mock_client.return_value.collection.return_value.document.return_value.update.side_effect = Exception("network")
    with pytest.raises(FirestoreError):
        complete_job("j1", {}, "name")


@patch("utils.firebase.firestore_client")
def test_complete_job_unconditionally_clears_top_level_input_text(mock_client):
    """complete_job always deletes the top-level input_text field — this app
    never keeps the raw document text around after a job reaches a terminal
    state (see complete_job's own docstring)."""
    from utils.firebase import complete_job
    from firebase_admin import firestore

    doc_ref = MagicMock()
    mock_client.return_value.collection.return_value.document.return_value = doc_ref

    complete_job("j1", {"care_plan": {}}, "name")

    update_fields = doc_ref.update.call_args.args[0]
    assert update_fields["input_text"] is firestore.DELETE_FIELD
    assert update_fields["status"] == "completed"


@patch("utils.firebase.firestore_client")
def test_fail_job_raises_firestore_error(mock_client):
    from utils.firebase import fail_job, FirestoreError
    mock_client.return_value.collection.return_value.document.return_value.update.side_effect = Exception("network")
    with pytest.raises(FirestoreError):
        fail_job("j1", {})


@patch("utils.firebase.firestore_client")
def test_fail_job_unconditionally_clears_top_level_input_text(mock_client):
    """fail_job always deletes the top-level input_text field too — the raw
    text is no longer needed once a job reaches ANY terminal state."""
    from utils.firebase import fail_job
    from firebase_admin import firestore

    doc_ref = MagicMock()
    mock_client.return_value.collection.return_value.document.return_value = doc_ref

    fail_job("j1", {"code": "EMPTY_DOCUMENT"})

    update_fields = doc_ref.update.call_args.args[0]
    assert update_fields["input_text"] is firestore.DELETE_FIELD
    assert update_fields["status"] == "error"


@patch("utils.firebase.firestore_client")
def test_get_job_doc_raises_firestore_error(mock_client):
    from utils.firebase import get_job_doc, FirestoreError
    mock_client.return_value.collection.return_value.document.return_value.get.side_effect = Exception("network")
    with pytest.raises(FirestoreError):
        get_job_doc("j1")


# ---------------------------------------------------------------------------
# verify_firebase_token — anonymous-caller deny-by-default (Finding 1)
# ---------------------------------------------------------------------------

def _build_app_with_route(allow_anonymous=None):
    """Build a minimal Flask app with one route guarded by verify_firebase_token.

    allow_anonymous=None -> bare @verify_firebase_token (deny-by-default).
    allow_anonymous=True/False -> @verify_firebase_token(allow_anonymous=...).
    """
    from utils.firebase import verify_firebase_token
    from flask import g, jsonify

    app = Flask(__name__)

    if allow_anonymous is None:
        @app.route("/protected", methods=["POST"])
        @verify_firebase_token
        def protected(user_id):
            return jsonify({"user_id": user_id, "is_anonymous": g.get("is_anonymous")})
    else:
        @app.route("/protected", methods=["POST"])
        @verify_firebase_token(allow_anonymous=allow_anonymous)
        def protected(user_id):
            return jsonify({"user_id": user_id, "is_anonymous": g.get("is_anonymous")})

    return app


def _anonymous_decoded_token(uid="anon-1"):
    return {"uid": uid, "firebase": {"sign_in_provider": "anonymous", "identities": {}}}


def _password_decoded_token(uid="user-1"):
    return {"uid": uid, "firebase": {"sign_in_provider": "password", "identities": {}}}


def test_verify_firebase_token_rejects_anonymous_by_default():
    app = _build_app_with_route(allow_anonymous=None)
    client = app.test_client()

    with patch("utils.firebase.auth.verify_id_token", lambda *a, **k: _anonymous_decoded_token()):
        resp = client.post("/protected", headers={"Authorization": "Bearer tok"})

    assert resp.status_code == 403
    body = resp.get_json()
    assert body["error"]["code"] == "ANONYMOUS_ACCESS_FORBIDDEN"


def test_verify_firebase_token_accepts_non_anonymous_by_default():
    app = _build_app_with_route(allow_anonymous=None)
    client = app.test_client()

    with patch("utils.firebase.auth.verify_id_token", lambda *a, **k: _password_decoded_token()):
        resp = client.post("/protected", headers={"Authorization": "Bearer tok"})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["user_id"] == "user-1"
    assert body["is_anonymous"] is False


def test_verify_firebase_token_accepts_token_with_no_firebase_claim():
    """Tokens with no 'firebase' claim at all (e.g. simple test mocks) are
    treated as non-anonymous — only an explicit anonymous provider is denied."""
    app = _build_app_with_route(allow_anonymous=None)
    client = app.test_client()

    with patch("utils.firebase.auth.verify_id_token", lambda *a, **k: {"uid": "user-1"}):
        resp = client.post("/protected", headers={"Authorization": "Bearer tok"})

    assert resp.status_code == 200
    assert resp.get_json()["is_anonymous"] is False


def test_verify_firebase_token_allow_anonymous_true_accepts_anonymous():
    app = _build_app_with_route(allow_anonymous=True)
    client = app.test_client()

    with patch("utils.firebase.auth.verify_id_token", lambda *a, **k: _anonymous_decoded_token()):
        resp = client.post("/protected", headers={"Authorization": "Bearer tok"})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["user_id"] == "anon-1"
    assert body["is_anonymous"] is True


def test_verify_firebase_token_allow_anonymous_true_still_accepts_non_anonymous():
    app = _build_app_with_route(allow_anonymous=True)
    client = app.test_client()

    with patch("utils.firebase.auth.verify_id_token", lambda *a, **k: _password_decoded_token()):
        resp = client.post("/protected", headers={"Authorization": "Bearer tok"})

    assert resp.status_code == 200
    assert resp.get_json()["is_anonymous"] is False


def test_verify_firebase_token_allow_anonymous_false_explicit_rejects_anonymous():
    app = _build_app_with_route(allow_anonymous=False)
    client = app.test_client()

    with patch("utils.firebase.auth.verify_id_token", lambda *a, **k: _anonymous_decoded_token()):
        resp = client.post("/protected", headers={"Authorization": "Bearer tok"})

    assert resp.status_code == 403
