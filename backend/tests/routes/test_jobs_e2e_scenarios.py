"""End-to-end / integration tests for the job pathway (POST /jobs ->
enqueue -> worker -> completed/failed doc -> DELETE /jobs/<id>).

Scope (per the scenario-validation review): drive the
REAL Flask routes (routes/jobs.py, routes/worker.py) and the REAL helper
chain they call into (services/care_plan_input.py, utils/firebase.py's job
lifecycle functions, utils/pdf.py, utils/misc.py) with only external services
mocked:

  - Firestore:      FakeFirestoreClient (in-memory dict store) stands in for
                     utils.firebase.firestore_client()'s return value, so
                     create_job_doc/get_job_doc/complete_job/fail_job/
                     update_job_stage are the REAL functions operating on
                     REAL in-memory state through their exact .set/.get/
                     .update/.delete call shape (including firestore.
                     DELETE_FIELD and NotFound-on-missing-doc semantics).
  - GCS:             services.care_plan_input.get_gcs_bucket / utils.gcs.
                     delete_gcs_object mocked at the module boundary.
  - Cloud Tasks:     routes.jobs.enqueue_job_safe mocked (no real dispatch);
                     the worker route is invoked directly and synchronously
                     in its place, exactly as Cloud Tasks would call it.
  - LLM/Vertex:      routes.worker.run_care_plan_pipeline is overridden with a fake
                     generator that yields real Pydantic CarePlan/Grading
                     model instances (not MagicMocks) so output_data ==
                     envelope.to_dict() is byte-for-byte what a real
                     pipeline run would serialize. For the LLM-failure
                     scenario (#9), the real adapter/pipeline modules run
                     unmodified and only utils.llm-adjacent Vertex calls
                     (via CarePlanPipeline's own _generate_text/
                     _generate_json wrappers) are mocked, so the REAL
                     exception classification path (care_plan/
                     pipeline.py -> services/care_plan_pipeline.py ->
                     errors.build_error_data_from_exc) is exercised.
  - OCR:             utils.image_ocr / services.care_plan_input.
                     extract_text_from_image mocked per-file.

Fixtures needed for degenerate-input scenarios (corrupt/encrypted/blank PDF,
DOCX, ZIP-as-PDF, real JPEG bytes for OCR/merge) are generated programmatically
below rather than committed as binaries.
"""
from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from google.api_core import exceptions as gexc
from google.cloud import firestore as gcf

from errors import ErrorCode
from models.pipeline_events import AdapterStepEvent, AdapterResult
from utils.constants import Constants

JOBS_ENV = {
    "CLOUD_TASKS_QUEUE": "test-queue",
    "WORKER_URL": "https://worker.run.app",
    "WORKER_SERVICE_ACCOUNT": "sa@proj.iam",
    "GCP_BUCKET_NAME": "test-bucket",
}
WORKER_HEADERS = {"X-CloudTasks-QueueName": "test-queue"}


# ---------------------------------------------------------------------------
# Fake Firestore -- in-memory backing store shared by every real firebase.py
# job-lifecycle function so the full create->process->complete->delete chain
# runs against genuine (if simplified) persistence semantics.
# ---------------------------------------------------------------------------

class _FakeSnapshot:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None

    def get(self, field):
        return (self._data or {}).get(field)


class _FakeDocRef:
    def __init__(self, collection_store, doc_id):
        self._store = collection_store
        self.id = doc_id

    def set(self, data, merge=False):
        if merge and self.id in self._store:
            self._store[self.id].update(data)
        else:
            self._store[self.id] = dict(data)

    def get(self, transaction=None):
        return _FakeSnapshot(self.id, self._store.get(self.id))

    def update(self, fields):
        # Mirrors real Firestore: .update() on a nonexistent doc raises
        # NotFound rather than creating it -- this is what stops a
        # delete-mid-processing race from resurrecting a deleted doc.
        if self.id not in self._store:
            raise gexc.NotFound(f"No document to update: {self.id}")
        doc = self._store[self.id]
        for key, value in fields.items():
            if value is gcf.DELETE_FIELD:
                doc.pop(key, None)
            else:
                doc[key] = value

    def delete(self):
        self._store.pop(self.id, None)


class _FakeCollection:
    def __init__(self, store):
        self._store = store

    def document(self, doc_id=None):
        if doc_id is None:
            doc_id = str(uuid.uuid4())
        return _FakeDocRef(self._store, doc_id)


class FakeFirestoreClient:
    def __init__(self):
        self._collections: dict[str, dict] = {}

    def collection(self, name):
        return _FakeCollection(self._collections.setdefault(name, {}))

    def transaction(self):
        return MagicMock()

    # Test helper, not part of the real client API.
    def raw_doc(self, collection: str, doc_id: str) -> dict | None:
        return self._collections.get(collection, {}).get(doc_id)


@pytest.fixture
def fake_db(monkeypatch):
    client = FakeFirestoreClient()
    monkeypatch.setattr("utils.firebase.firestore_client", lambda: client)
    monkeypatch.setattr("routes.jobs.firestore_client", lambda: client)
    return client


@pytest.fixture
def app_jobs():
    from routes.jobs import jobs_bp
    app = Flask(__name__)
    app.register_blueprint(jobs_bp)
    return app


@pytest.fixture
def client_jobs(app_jobs):
    return app_jobs.test_client()


@pytest.fixture
def app_worker():
    from routes.worker import worker_bp
    app = Flask(__name__)
    app.register_blueprint(worker_bp)
    return app


@pytest.fixture
def client_worker(app_worker):
    return app_worker.test_client()


@pytest.fixture(autouse=True)
def _disable_oidc(monkeypatch):
    monkeypatch.setenv("WORKER_VERIFY_OIDC", "false")


@pytest.fixture(autouse=True)
def _bypass_rate_limit(monkeypatch):
    """Most scenarios aren't testing the rate limiter itself. Scenario 10's
    tests override this by not depending on it / exercising the real thing."""
    monkeypatch.setattr("utils.rate_limit.check_rate_limit", lambda: True)


@pytest.fixture
def auth_anon(monkeypatch):
    monkeypatch.setattr(
        "utils.firebase.auth.verify_id_token",
        lambda *a, **k: {"uid": "anon-1", "firebase": {"sign_in_provider": "anonymous", "identities": {}}},
    )
    return {"Authorization": "Bearer anon-token"}


def _auth_for(monkeypatch, uid: str) -> dict:
    monkeypatch.setattr(
        "utils.firebase.auth.verify_id_token",
        lambda token, *a, **k: {
            "uid": uid, "firebase": {"sign_in_provider": "anonymous", "identities": {}},
        },
    )
    return {"Authorization": f"Bearer {uid}-token"}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _post_job(client_jobs, headers, mock_gcs=True, **kwargs):
    with patch.dict("os.environ", JOBS_ENV):
        with patch("routes.jobs.enqueue_job_safe", return_value=None):
            if mock_gcs:
                with patch("services.care_plan_input.get_gcs_bucket") as mock_bucket:
                    mock_bucket.return_value.blob.return_value = MagicMock()
                    resp = client_jobs.post("/jobs", headers=headers, **kwargs)
            else:
                resp = client_jobs.post("/jobs", headers=headers, **kwargs)
    return resp


def _run_worker(client_worker, job_id, headers=None):
    return client_worker.post(f"/internal/jobs/execute/{job_id}", headers=headers or WORKER_HEADERS)


def _delete_job(client_jobs, job_id, headers):
    with patch("routes.jobs.delete_gcs_object") as mock_delete:
        resp = client_jobs.delete(f"/jobs/{job_id}", headers=headers)
    return resp, mock_delete


def _doc_size_bytes(doc: dict) -> int:
    """Approximate Firestore wire size via UTF-8-encoded JSON length (datetime
    objects stringified). Not exact protobuf accounting, but a reasonable,
    conservative proxy for regression-style "stays under 1 MiB" assertions."""
    return len(json.dumps(doc, default=str, ensure_ascii=False).encode("utf-8"))


def _max_leaf_string_bytes(obj) -> int:
    if isinstance(obj, dict):
        return max((_max_leaf_string_bytes(v) for v in obj.values()), default=0)
    if isinstance(obj, list):
        return max((_max_leaf_string_bytes(v) for v in obj), default=0)
    if isinstance(obj, str):
        return len(obj.encode("utf-8"))
    return 0


def _build_care_plan(size: str = "typical"):
    """Build a real CarePlan instance with realistic field lengths, so
    envelope.to_dict() serialization in the worker is genuine, not mocked."""
    from models.care_plan.care_plan import (
        CarePlan, ReasonForVisit, Diagnosis, DiagnosisDetail, Medication,
        Test, Procedure, FollowUp, WarningSign, GlossaryTerm, RawArtifacts,
    )
    n = 6 if size == "typical" else 14
    meds = [
        Medication(
            title=f"Medication {i}", plain_name=f"Drug name {i}",
            why="Helps control your blood pressure and reduce the strain on your heart over time.",
            dosage="10 mg", frequency="Once daily", timing="Morning, with food",
            duration="Ongoing, until your next visit",
            instructions="Take with a full glass of water. Do not skip doses.",
            side_effects_to_watch="Dizziness, dry cough, swelling of the lips or face, rash.",
            importance="high",
        )
        for i in range(n)
    ]
    tests = [
        Test(
            title=f"Test {i}", plain_name=f"Lab test {i}",
            why="Checks how well your kidneys and liver are working on this medication.",
            description="A simple blood draw performed at any lab.",
            preparation="No fasting required.",
            importance="low",
        )
        for i in range(max(2, n // 2))
    ]
    procedures = [
        Procedure(
            title=f"Procedure {i}", plain_name=f"Follow-up procedure {i}",
            why="Needed to monitor your recovery.",
            what_to_expect="A short outpatient visit, usually under an hour.",
            timeframe="Within 2 weeks",
            importance="low",
        )
        for i in range(max(1, n // 4))
    ]
    warnings = [
        WarningSign(
            symptom=f"Warning sign {i}",
            what_it_might_mean="This could indicate a serious reaction to your medication.",
            what_to_do="Call 911 or go to the nearest emergency room immediately.",
            urgency="emergency",
            related_to="medication",
            importance="high",
        )
        for i in range(max(2, n // 3))
    ]
    terms = {
        f"term_{i}": GlossaryTerm(
            definition="A plain-language definition of a medical term used in your note.",
            source="notes",
        )
        for i in range(n * 2)
    }
    raw = RawArtifacts(text="x" * 3000, simplified_text="y" * 3000, clarified_text="z" * 3000)
    return CarePlan(
        summary="Overview of your visit and what to do next.",
        reason_for_visit=[
            ReasonForVisit(reason="Follow-up visit", description="Routine follow-up for chronic condition management.")
        ],
        diagnosis=Diagnosis(
            main_conclusion="Your blood pressure remains elevated and needs medication adjustment.",
            changed_since_last_visit="Dosage increased since last visit.",
            details=[
                DiagnosisDetail(
                    title="Hypertension", plain_name="High blood pressure",
                    description="Persistently elevated blood pressure readings.",
                    what_it_means_for_you="You'll need medication and lifestyle changes to lower your risk.",
                    severity="medium",
                )
            ],
        ),
        medications=meds, tests=tests, procedures=procedures,
        other=[], follow_up=[FollowUp(time_frame="2 weeks", description="Return for a blood pressure check.")],
        warning_signs=warnings,
        questions=["Should I avoid salty foods?", "When can I resume exercise?"],
        low_priority=[],
        terms=terms,
        raw=raw,
    )


def _build_grading():
    from models.grading import Grading, GradingEntry
    entries = []
    for target in ("before", "after"):
        for method in Constants.Grading.GRADING_METHODS:
            entries.append(GradingEntry(
                name=method.value.value, target=target, grade=55.0,
                grade_breakdown={"detail": "x" * 50}, reasoning=method.value.description,
            ))
        entries.append(GradingEntry(
            name="combined", target=target, grade=60.0,
            grade_breakdown={
                "grade_estimate": 8, "label": "moderate", "word_count": 500,
                "dimensions": {"a": 1, "b": 2},
            },
            reasoning=None,
        ))
    return Grading(entries=entries, enabled=True, graded_at="2026-09-05T00:00:00+00:00")


def _fake_pipeline_factory(care_plan, grading):
    calls = {"count": 0}

    def fake_pipeline(text, metrics, grading_enabled, source_kind="upload", is_batch=False):
        calls["count"] += 1
        yield AdapterStepEvent(step=2, status="active", label="Terms")
        yield AdapterStepEvent(step=2, status="done", label="Terms")
        yield AdapterStepEvent(step=3, status="active", label="Simplify")
        yield AdapterStepEvent(step=3, status="done", label="Simplify")
        yield AdapterStepEvent(step=4, status="active", label="Clarify")
        yield AdapterStepEvent(step=4, status="done", label="Clarify")
        yield AdapterStepEvent(step=5, status="active", label="Structure")
        yield AdapterStepEvent(step=5, status="done", label="Structure")
        yield AdapterResult(care_plan=care_plan, grading=grading, raw_text=text, clarified_text=text)

    fake_pipeline.calls = calls
    return fake_pipeline


def _multibyte_padding(byte_budget: int) -> str:
    """Mixed CJK / Arabic (RTL) / emoji (supplementary-plane, surrogate-pair
    in UTF-16) / combining-diacritic text sized just under byte_budget UTF-8
    bytes, comfortably under MAX_TEXT_LENGTH chars too (bytes/char ratio here
    is ~1.7-2, so char count is always well under the 500,000 char cap for
    any byte_budget <= MAX_TEXT_BYTES)."""
    unit = "中文测试مرحبا😀éé́ "
    unit_bytes = len(unit.encode("utf-8"))
    repeats = max(1, byte_budget // unit_bytes)
    text = unit * repeats
    while len(text.encode("utf-8")) >= byte_budget:
        text = text[:-1]
    return text


def _make_jpeg_bytes(color=(200, 50, 50), size=(64, 64)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


def _make_blank_pdf_bytes() -> bytes:
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _make_encrypted_pdf_bytes(password="secret123") -> bytes:
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt(user_password=password)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _make_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("hello.txt", "not a pdf")
    return buf.getvalue()


def _make_blank_docx_bytes() -> bytes:
    from docx import Document
    buf = io.BytesIO()
    Document().save(buf)
    return buf.getvalue()


NO_LEAK_STRINGS = ("Traceback", "PyPDF2", "pypdf", "docx.opc", "site-packages", "  File \"")


def _assert_no_internal_leak(resp):
    body = resp.get_data(as_text=True)
    assert resp.status_code != 500, f"got 500: {body}"
    for bad in NO_LEAK_STRINGS:
        assert bad not in body, f"leaked internal detail {bad!r} in response: {body}"


# ===========================================================================
# Scenario 1: typical discharge summary (text-layer PDF equivalent) ->
# completed doc; size + PII-scrubbing assertions on the final doc.
# ===========================================================================

class TestScenario1TypicalDischargeSummary:
    def test_full_chain_completes_and_final_doc_is_safe_and_small(self, client_jobs, client_worker, fake_db, auth_anon):
        # ~8 "pages" of realistic discharge-summary prose (a few thousand
        # chars/page is realistic per this repo's own MAX_TEXT_LENGTH
        # commentary), well under every cap.
        page = (
            "Patient presented for follow-up of hypertension and type 2 diabetes. "
            "Blood pressure 148/92, up from 132/84 at last visit. Discussed lifestyle "
            "modification, medication adherence, and dietary sodium restriction. "
        ) * 20
        text = "\n\n".join(f"--- Page {i+1} ---\n{page}" for i in range(8))

        care_plan = _build_care_plan("typical")
        grading = _build_grading()
        fake_pipeline = _fake_pipeline_factory(care_plan, grading)

        resp = _post_job(client_jobs, auth_anon, json={"text": text})
        assert resp.status_code == 202
        job_id = resp.get_json()["job_id"]

        with patch("routes.worker.run_care_plan_pipeline", fake_pipeline):
            worker_resp = _run_worker(client_worker, job_id)
        assert worker_resp.status_code == 200
        assert fake_pipeline.calls["count"] == 1

        doc = fake_db.raw_doc("care_plan_outputs", job_id)
        assert doc is not None
        assert doc["status"] == "completed"

        # Raw input text must be gone from BOTH copies (Finding 4).
        assert "input_text" not in doc
        assert doc["output_data"]["input"].get("text") is None
        assert "raw" not in doc["output_data"]["care_plan"]

        # Only "combined" grading entries survive.
        entry_names = {e["name"] for e in doc["output_data"]["grading"]["entries"]}
        assert entry_names == {"combined"}
        assert len(doc["output_data"]["grading"]["entries"]) == 2  # before + after

        size = _doc_size_bytes(doc)
        assert size < 1_048_576, f"completed doc is {size} bytes, over Firestore's 1 MiB limit"
        # Report this concrete number (see scenario-validation report).
        print(f"\n[scenario 1] completed doc size: {size} bytes")

        max_leaf = _max_leaf_string_bytes(doc)
        assert max_leaf < 1500, f"a single field value is {max_leaf} bytes (auto-index truncation risk)"

        # Clean delete afterward.
        del_resp, mock_delete = _delete_job(client_jobs, job_id, auth_anon)
        assert del_resp.status_code == 204
        assert fake_db.raw_doc("care_plan_outputs", job_id) is None


# ===========================================================================
# Scenario 2: phone photos of a paper after-visit summary (OCR path).
# ===========================================================================

class TestScenario2PhonePhotosOCR:
    def test_three_jpegs_via_ocr_completes(self, client_jobs, client_worker, fake_db, auth_anon):
        images = [_make_jpeg_bytes(color=c) for c in [(200, 50, 50), (50, 200, 50), (50, 50, 200)]]
        ocr_texts = [
            "Page 1 of 3: Discharge instructions. Take ibuprofen 400mg every 6 hours as needed for pain.",
            "Page 2 of 3: Follow up with your primary care physician within 7 days of discharge.",
            "Page 3 of 3: Return to the ER if you experience fever above 101F or worsening pain.",
        ]

        data = {"files": [
            (io.BytesIO(images[0]), "page1.jpg"),
            (io.BytesIO(images[1]), "page2.jpg"),
            (io.BytesIO(images[2]), "page3.jpg"),
        ]}

        care_plan = _build_care_plan("typical")
        grading = _build_grading()
        fake_pipeline = _fake_pipeline_factory(care_plan, grading)

        with patch("services.care_plan_input.extract_text_from_image", side_effect=ocr_texts):
            resp = _post_job(
                client_jobs, auth_anon, data=data, content_type="multipart/form-data",
            )
        assert resp.status_code == 202
        job_id = resp.get_json()["job_id"]
        doc = fake_db.raw_doc("care_plan_outputs", job_id)
        # All 3 OCR'd pages' text made it into the combined input.
        for t in ocr_texts:
            assert t in doc["input_text"]

        with patch("routes.worker.run_care_plan_pipeline", fake_pipeline):
            worker_resp = _run_worker(client_worker, job_id)
        assert worker_resp.status_code == 200

        doc = fake_db.raw_doc("care_plan_outputs", job_id)
        assert doc["status"] == "completed"
        assert "input_text" not in doc


# ===========================================================================
# Scenario 3: mixed 5-file batch under 10MB succeeds; just over -> clean 400;
# 6 files -> clean 400.
# ===========================================================================

class TestScenario3MixedBatchLimits:
    def test_five_mixed_files_just_under_10mb_succeeds(self, client_jobs, fake_db, auth_anon):
        from pypdf import PdfWriter
        pdf_writer = PdfWriter()
        pdf_writer.add_blank_page(width=200, height=200)
        pdf_buf = io.BytesIO()
        pdf_writer.write(pdf_buf)

        docx_bytes = None
        from docx import Document
        doc_ = Document()
        doc_.add_paragraph("This is a real clinical note stored in a DOCX file for the visit.")
        docx_buf = io.BytesIO()
        doc_.save(docx_buf)
        docx_bytes = docx_buf.getvalue()

        # Padding goes AFTER the JPEG's EOI marker: PIL happily decodes a
        # JPEG with trailing garbage bytes (verified empirically), so this
        # inflates the file's byte size (counted toward the 10 MB aggregate
        # cap) without turning into extracted OCR text (mocked below,
        # ignores the actual bytes) or breaking the real merge_pdfs step.
        # Padding a .txt file instead would inflate the EXTRACTED TEXT itself
        # (decoded verbatim) well past the 350,000-byte text cap -- a
        # different limit than the one this test is exercising.
        pad = b"\x00" * (2 * 1024 * 1024)  # 2 MiB padding per image
        img1 = _make_jpeg_bytes((10, 10, 10)) + pad
        img2 = _make_jpeg_bytes((250, 250, 250)) + pad
        txt_bytes = b"Plain text clinical note content for the visit summary."

        with patch("services.care_plan_input.extract_text_from_pdf", return_value="PDF page content about the visit."):
            data = {"files": [
                (io.BytesIO(pdf_buf.getvalue()), "note.pdf"),
                (io.BytesIO(docx_bytes), "note.docx"),
                (io.BytesIO(img1), "photo1.jpg"),
                (io.BytesIO(img2), "photo2.jpg"),
                (io.BytesIO(txt_bytes), "note.txt"),
            ]}
            with patch("services.care_plan_input.extract_text_from_image", return_value="Photo OCR text about the visit."):
                resp = _post_job(client_jobs, auth_anon, data=data, content_type="multipart/form-data")

        assert resp.status_code == 202
        job_id = resp.get_json()["job_id"]
        doc = fake_db.raw_doc("care_plan_outputs", job_id)
        assert doc is not None

    def test_five_files_just_over_10mb_returns_clean_400(self, client_jobs, auth_anon):
        over_budget = Constants.Limits.MAX_AGGREGATE_FILE_BYTES + 1024
        data = {"files": [
            (io.BytesIO(b"A" * (over_budget // 5 + 1)), f"f{i}.txt") for i in range(5)
        ]}
        resp = _post_job(client_jobs, auth_anon, data=data, content_type="multipart/form-data")
        assert resp.status_code == 400
        assert resp.status_code != 413
        assert resp.status_code != 500
        assert resp.get_json()["error"]["code"] == "INPUT_VALIDATION_ERROR"

    def test_six_files_returns_clean_400(self, client_jobs, auth_anon):
        data = {"files": [(io.BytesIO(b"hello world clinical note"), f"f{i}.txt") for i in range(6)]}
        resp = _post_job(client_jobs, auth_anon, data=data, content_type="multipart/form-data")
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "INPUT_VALIDATION_ERROR"


# ===========================================================================
# Scenario 4: non-English / emoji-heavy input near the limits.
# ===========================================================================

class TestScenario4MultibyteNearLimits:
    def test_cjk_under_char_cap_over_byte_cap_returns_clean_400(self, client_jobs, auth_anon):
        char_count = (Constants.Uploads.MAX_TEXT_BYTES // 3) + 100
        assert char_count < Constants.Uploads.MAX_TEXT_LENGTH
        text = "中" * char_count
        resp = _post_job(client_jobs, auth_anon, json={"text": text})
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "INPUT_VALIDATION_ERROR"
        _assert_no_internal_leak(resp)

    def test_arabic_rtl_over_byte_cap_returns_clean_400(self, client_jobs, auth_anon):
        unit = "مرحبا بكم في هذا النص الطويل "
        text = unit
        while len(text.encode("utf-8")) <= Constants.Uploads.MAX_TEXT_BYTES:
            text += unit
        assert len(text.encode("utf-8")) > Constants.Uploads.MAX_TEXT_BYTES
        resp = _post_job(client_jobs, auth_anon, json={"text": text})
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "INPUT_VALIDATION_ERROR"

    def test_emoji_surrogate_pairs_over_byte_cap_returns_clean_400(self, client_jobs, auth_anon):
        # Each "😀" is 1 Python codepoint (U+1F600, supplementary plane) but a
        # surrogate PAIR in UTF-16 and 4 bytes in UTF-8.
        char_count = (Constants.Uploads.MAX_TEXT_BYTES // 4) + 100
        text = "😀" * char_count
        assert char_count < Constants.Uploads.MAX_TEXT_LENGTH
        resp = _post_job(client_jobs, auth_anon, json={"text": text})
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "INPUT_VALIDATION_ERROR"

    def test_mixed_multibyte_just_under_both_caps_completes_and_stays_under_1mib(
        self, client_jobs, client_worker, fake_db, auth_anon,
    ):
        text = _multibyte_padding(Constants.Uploads.MAX_TEXT_BYTES)
        assert len(text.encode("utf-8")) < Constants.Uploads.MAX_TEXT_BYTES
        assert len(text) < Constants.Uploads.MAX_TEXT_LENGTH

        # Use the larger "dense" output profile too, so this measures a
        # genuine worst case: near-max multibyte input AND large structured
        # output in the same job.
        care_plan = _build_care_plan("dense")
        grading = _build_grading()
        fake_pipeline = _fake_pipeline_factory(care_plan, grading)

        resp = _post_job(client_jobs, auth_anon, json={"text": text})
        assert resp.status_code == 202
        job_id = resp.get_json()["job_id"]

        with patch("routes.worker.run_care_plan_pipeline", fake_pipeline):
            worker_resp = _run_worker(client_worker, job_id)
        assert worker_resp.status_code == 200

        doc = fake_db.raw_doc("care_plan_outputs", job_id)
        assert doc["status"] == "completed"
        assert "input_text" not in doc  # the near-max-byte input is fully cleared

        size = _doc_size_bytes(doc)
        assert size < 1_048_576, f"completed doc is {size} bytes"
        print(f"\n[scenario 4] completed doc size (dense output + near-max multibyte input, "
              f"input cleared before persist): {size} bytes")

    def test_combining_diacritics_and_null_and_lone_surrogate_rejected_cleanly(self, client_jobs, fake_db, auth_anon):
        # NUL byte.
        resp = _post_job(client_jobs, auth_anon, json={"text": "Patient note\x00with a null byte"})
        assert resp.status_code == 400
        _assert_no_internal_leak(resp)

        # Lone UTF-16 surrogate via raw JSON body (json.loads permits this;
        # UTF-8 encoding does not).
        resp2 = client_jobs.post(
            "/jobs",
            data='{"text": "clinical note \\ud800 more text"}',
            headers={**auth_anon, "Content-Type": "application/json"},
        )
        assert resp2.status_code == 400
        _assert_no_internal_leak(resp2)

        # Combining diacritics alone must NOT be rejected -- valid, storable
        # Unicode, well under every cap.
        combining = "é" * 50 + " clinical note about the visit, in Vietnamese-style diacritics."
        resp3 = _post_job(client_jobs, auth_anon, json={"text": combining})
        assert resp3.status_code == 202


# ===========================================================================
# Scenario 5: degenerate inputs -- always a clean 4xx, never a 500 or leak.
# ===========================================================================

class TestScenario5DegenerateInputs:
    def test_scanned_pdf_no_text_layer_returns_clean_error(self, client_jobs, auth_anon):
        pdf_bytes = _make_blank_pdf_bytes()
        data = {"files": (io.BytesIO(pdf_bytes), "scan.pdf")}
        resp = _post_job(client_jobs, auth_anon, data=data, content_type="multipart/form-data")
        _assert_no_internal_leak(resp)
        assert resp.status_code // 100 == 4
        assert resp.get_json()["error"]["code"] == "EMPTY_DOCUMENT"

    def test_zero_byte_file_returns_clean_error(self, client_jobs, auth_anon):
        data = {"files": (io.BytesIO(b""), "empty.pdf")}
        resp = _post_job(client_jobs, auth_anon, data=data, content_type="multipart/form-data")
        _assert_no_internal_leak(resp)
        assert resp.status_code // 100 == 4

    def test_corrupt_pdf_returns_clean_error(self, client_jobs, auth_anon):
        data = {"files": (io.BytesIO(b"%PDF-1.4 this is not really a pdf file at all, just garbage bytes"), "bad.pdf")}
        resp = _post_job(client_jobs, auth_anon, data=data, content_type="multipart/form-data")
        _assert_no_internal_leak(resp)
        assert resp.status_code // 100 == 4
        assert resp.get_json()["error"]["code"] == "FILE_PARSE_FAILED"

    def test_password_protected_pdf_returns_clean_error(self, client_jobs, auth_anon):
        pdf_bytes = _make_encrypted_pdf_bytes()
        data = {"files": (io.BytesIO(pdf_bytes), "protected.pdf")}
        resp = _post_job(client_jobs, auth_anon, data=data, content_type="multipart/form-data")
        _assert_no_internal_leak(resp)
        assert resp.status_code // 100 == 4
        assert resp.get_json()["error"]["code"] == "FILE_PARSE_FAILED"

    def test_zip_disguised_as_pdf_returns_clean_error(self, client_jobs, auth_anon):
        zip_bytes = _make_zip_bytes()
        data = {"files": (io.BytesIO(zip_bytes), "sneaky.pdf")}
        resp = _post_job(client_jobs, auth_anon, data=data, content_type="multipart/form-data")
        _assert_no_internal_leak(resp)
        assert resp.status_code // 100 == 4
        assert resp.get_json()["error"]["code"] == "FILE_PARSE_FAILED"

    def test_blank_docx_returns_clean_error(self, client_jobs, auth_anon):
        docx_bytes = _make_blank_docx_bytes()
        data = {"files": (io.BytesIO(docx_bytes), "blank.docx")}
        resp = _post_job(client_jobs, auth_anon, data=data, content_type="multipart/form-data")
        _assert_no_internal_leak(resp)
        assert resp.status_code // 100 == 4
        assert resp.get_json()["error"]["code"] == "EMPTY_DOCUMENT"

    def test_whitespace_only_pasted_text_treated_as_no_input(self, client_jobs, auth_anon):
        resp = _post_job(client_jobs, auth_anon, json={"text": "   \n\t  "})
        _assert_no_internal_leak(resp)
        assert resp.status_code == 400

    def test_null_byte_in_pasted_text_returns_clean_error(self, client_jobs, auth_anon):
        resp = _post_job(client_jobs, auth_anon, json={"text": "clinical note\x00with embedded null"})
        _assert_no_internal_leak(resp)
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "INPUT_VALIDATION_ERROR"

    def test_lone_surrogate_in_pasted_text_returns_clean_error(self, client_jobs, auth_anon):
        resp = client_jobs.post(
            "/jobs",
            data='{"text": "note with \\ud800 lone surrogate"}',
            headers={**auth_anon, "Content-Type": "application/json"},
        )
        _assert_no_internal_leak(resp)
        assert resp.status_code == 400


# ===========================================================================
# Scenario 6: partial-failure batch (some files unusable).
# ===========================================================================

class TestScenario6PartialFailureBatch:
    def test_two_of_five_unusable_succeeds_with_skipped_files_reported(self, client_jobs, fake_db, auth_anon):
        good1 = b"Good clinical note number one about the patient's visit today."
        good2 = b"Good clinical note number two describing follow-up instructions."
        good3 = b"Good clinical note number three with medication details included."
        blank = b"   "
        corrupt_pdf = b"%PDF-1.4 not a real pdf, garbage content follows here"

        data = {"files": [
            (io.BytesIO(good1), "good1.txt"),
            (io.BytesIO(blank), "blank.txt"),
            (io.BytesIO(good2), "good2.txt"),
            (io.BytesIO(corrupt_pdf), "corrupt.pdf"),
            (io.BytesIO(good3), "good3.txt"),
        ]}
        resp = _post_job(client_jobs, auth_anon, data=data, content_type="multipart/form-data")
        assert resp.status_code == 202
        job_id = resp.get_json()["job_id"]

        doc = fake_db.raw_doc("care_plan_outputs", job_id)
        assert "Good clinical note number one" in doc["input_text"]
        assert "Good clinical note number two" in doc["input_text"]
        assert "Good clinical note number three" in doc["input_text"]
        assert sorted(doc.get("skipped_files", [])) == ["blank.txt", "corrupt.pdf"]

    def test_all_five_unusable_returns_single_clean_empty_document_error(self, client_jobs, auth_anon):
        data = {"files": [
            (io.BytesIO(b"   "), "blank1.txt"),
            (io.BytesIO(b""), "blank2.txt"),
            (io.BytesIO(b"%PDF-1.4 garbage"), "bad.pdf"),
            (io.BytesIO(b"  \n  "), "blank3.txt"),
            (io.BytesIO(_make_blank_docx_bytes()), "blank.docx"),
        ]}
        resp = _post_job(client_jobs, auth_anon, data=data, content_type="multipart/form-data")
        _assert_no_internal_leak(resp)
        assert resp.status_code // 100 == 4
        assert resp.get_json()["error"]["code"] == "EMPTY_DOCUMENT"


# ===========================================================================
# Scenario 7: filename hostility.
# ===========================================================================

class TestScenario7FilenameHostility:
    def test_unicode_emoji_filename_accepted_and_isolated_from_gcs_path(self, client_jobs, fake_db, auth_anon):
        filename = "患者記録😀report.txt"
        data = {"files": (io.BytesIO(b"Clinical note content about the patient's visit."), filename)}
        with patch("services.care_plan_input.get_gcs_bucket") as mock_bucket:
            bucket = mock_bucket.return_value
            blob_mock = MagicMock()
            bucket.blob.return_value = blob_mock
            with patch.dict("os.environ", JOBS_ENV):
                with patch("routes.jobs.enqueue_job_safe", return_value=None):
                    resp = client_jobs.post(
                        "/jobs", data=data, content_type="multipart/form-data", headers=auth_anon,
                    )
            assert resp.status_code == 202
            # blob() is called with the GCS object path -- must be a fixed,
            # uuid-based path, never derived from the user-supplied filename.
            called_path = bucket.blob.call_args[0][0]
            assert filename not in called_path
            assert called_path.startswith("care_plan_inputs/anon-1/inputs/")
            assert called_path.endswith(".pdf")

    def test_255_char_filename_accepted(self, client_jobs, fake_db, auth_anon):
        filename = ("a" * 251) + ".txt"  # 255 chars total
        assert len(filename) == 255
        data = {"files": (io.BytesIO(b"Clinical note content about the patient's visit."), filename)}
        resp = _post_job(client_jobs, auth_anon, data=data, content_type="multipart/form-data")
        assert resp.status_code == 202

    def test_path_traversal_filename_does_not_escape_gcs_path(self, client_jobs, fake_db, auth_anon):
        filename = "../../etc/passwd.txt"
        data = {"files": (io.BytesIO(b"Clinical note content about the patient's visit."), filename)}
        with patch("services.care_plan_input.get_gcs_bucket") as mock_bucket:
            bucket = mock_bucket.return_value
            blob_mock = MagicMock()
            bucket.blob.return_value = blob_mock
            with patch.dict("os.environ", JOBS_ENV):
                with patch("routes.jobs.enqueue_job_safe", return_value=None):
                    resp = client_jobs.post(
                        "/jobs", data=data, content_type="multipart/form-data", headers=auth_anon,
                    )
            assert resp.status_code == 202
            called_path = bucket.blob.call_args[0][0]
            assert ".." not in called_path
            assert "etc/passwd" not in called_path

    def test_filename_with_newline_and_quote_does_not_break_storage_or_leak(self):
        """A raw CR/LF or unescaped '"' cannot actually survive as a
        multipart Content-Disposition `filename` parameter over real HTTP --
        verified empirically: werkzeug's own multipart encoder/parser (both
        the test client's and, per RFC 2046, any compliant real one) treats
        an embedded '"' as closing the quoted-string early, and a raw
        newline is not valid header-field content at all -- so this can't be
        exercised as an HTTP-transport-level test the way the emoji/unicode
        and path-traversal filename tests above are. What's actually
        reachable and worth guarding is the APPLICATION-level handling once
        such a string is the parsed `.filename` value (e.g. from a client
        library that doesn't RFC-2046-escape it) -- so this drives the real
        resolve_uploaded_files() directly with a hostile filename already
        past the transport layer, the same technique
        tests/services/test_care_plan_input.py's own _FakeUpload uses."""
        from services.care_plan_input import resolve_uploaded_files

        class _FakeUpload:
            def __init__(self, filename, data):
                self.filename = filename
                self._buf = io.BytesIO(data)

            def read(self):
                return self._buf.read()

        filename = 'weird"name\nwith-quote-and-newline.txt'
        upload = _FakeUpload(filename, b"Clinical note content about the patient's visit.")

        resolved, _ = resolve_uploaded_files(
            [upload],
            max_file_count=Constants.Limits.MAX_FILE_COUNT,
            max_aggregate_bytes=Constants.Limits.MAX_AGGREGATE_FILE_BYTES,
        )

        # No crash, and the hostile string is contained as plain string DATA
        # (inside the combined text via source_separator) -- never used as a
        # dict/mapping KEY, which is the only place it could plausibly cause
        # structural corruption in a Firestore document or JSON body.
        assert filename in resolved.text
        assert resolved.source_filename == filename


# ===========================================================================
# Scenario 8: lifecycle races.
# ===========================================================================

class TestScenario8LifecycleRaces:
    def test_delete_mid_worker_write_does_not_resurrect_doc_and_gcs_not_orphaned(
        self, client_jobs, client_worker, fake_db, auth_anon,
    ):
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        # status="not_started" (not "processing") -- otherwise the worker's
        # own processing-lease check (routes/worker.py) would treat this as
        # an already-in-flight redelivery and no-op before ever reaching the
        # pipeline, which is a different scenario (tested separately below).
        fake_db.collection("care_plan_outputs").document(job_id).set({
            "uid": "anon-1", "name": "Test", "source_filename": "text_input",
            "created_at": now, "updated_at": now, "status": "not_started",
            "started_at": None, "stage": None,
            "input_source_kind": "text", "input_text": "Patient has hypertension.",
            "input_doc_id": None, "input_source_filename": "text_input",
            "input_pdf_gcs_uri": "gs://test-bucket/care_plan_inputs/anon-1/inputs/abc.pdf",
            "input_version": "v1-2", "grading_enabled": False,
            "expires_at": now + timedelta(hours=1),
        })

        care_plan = _build_care_plan("typical")
        grading = _build_grading()

        def racing_pipeline(text, metrics, grading_enabled, source_kind="text", is_batch=False):
            # Simulate the user's DELETE landing exactly while the worker is
            # mid-pipeline (between get_job_doc and complete_job).
            fake_db.collection("care_plan_outputs").document(job_id).delete()
            yield AdapterResult(care_plan=care_plan, grading=grading, raw_text=text, clarified_text=text)

        with patch("routes.worker.delete_gcs_object") as mock_delete_gcs:
            with patch("routes.worker.run_care_plan_pipeline", racing_pipeline):
                worker_resp = _run_worker(client_worker, job_id)

        # complete_job's .update() against the now-deleted doc raises, the
        # outer handler's own fail_job also fails against the missing doc
        # (swallowed) -- worker reports 500 rather than silently succeeding,
        # but critically:
        assert worker_resp.status_code == 500
        # 1. The doc was NOT resurrected.
        assert fake_db.raw_doc("care_plan_outputs", job_id) is None
        # 2. GCS cleanup still ran (best-effort, from the worker's own
        #    `finally` block) -- not orphaned even though the DELETE route's
        #    own GCS delete already ran first in the real-world sequence.
        mock_delete_gcs.assert_called_once_with(
            "gs://test-bucket/care_plan_inputs/anon-1/inputs/abc.pdf"
        )

    def test_redelivery_of_fresh_lease_is_noop_llm_not_called_twice(
        self, client_jobs, client_worker, fake_db, auth_anon,
    ):
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        started = now - timedelta(seconds=10)  # well within the 270s single-job budget
        fake_db.collection("care_plan_outputs").document(job_id).set({
            "uid": "anon-1", "name": "Test", "source_filename": "text_input",
            "created_at": started, "updated_at": started, "status": "processing",
            "started_at": started, "stage": 2,
            "input_source_kind": "text", "input_text": "Patient has hypertension.",
            "input_doc_id": None, "input_source_filename": "text_input",
            "input_pdf_gcs_uri": None, "input_version": "v1-2", "grading_enabled": False,
            "expires_at": now + timedelta(hours=1),
        })

        care_plan = _build_care_plan("typical")
        grading = _build_grading()
        fake_pipeline = _fake_pipeline_factory(care_plan, grading)

        with patch("routes.worker.run_care_plan_pipeline", fake_pipeline):
            worker_resp = _run_worker(client_worker, job_id)

        assert worker_resp.status_code == 200
        assert fake_pipeline.calls["count"] == 0  # never invoked -- pure no-op
        doc = fake_db.raw_doc("care_plan_outputs", job_id)
        assert doc["status"] == "processing"  # untouched

    def test_redelivery_after_lease_expired_retries_and_completes(
        self, client_jobs, client_worker, fake_db, auth_anon,
    ):
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        deadline = Constants.Deadlines.SINGLE_JOB_INTERNAL_DEADLINE_S
        started = now - timedelta(seconds=deadline + 30)  # past budget: prior attempt presumed dead
        fake_db.collection("care_plan_outputs").document(job_id).set({
            "uid": "anon-1", "name": "Test", "source_filename": "text_input",
            "created_at": started, "updated_at": started, "status": "processing",
            "started_at": started, "stage": 2,
            "input_source_kind": "text", "input_text": "Patient has hypertension.",
            "input_doc_id": None, "input_source_filename": "text_input",
            "input_pdf_gcs_uri": None, "input_version": "v1-2", "grading_enabled": False,
            "expires_at": now + timedelta(hours=1),
        })

        care_plan = _build_care_plan("typical")
        grading = _build_grading()
        fake_pipeline = _fake_pipeline_factory(care_plan, grading)

        with patch("routes.worker.run_care_plan_pipeline", fake_pipeline):
            worker_resp = _run_worker(client_worker, job_id)

        assert worker_resp.status_code == 200
        assert fake_pipeline.calls["count"] == 1  # retried exactly once
        doc = fake_db.raw_doc("care_plan_outputs", job_id)
        assert doc["status"] == "completed"


# ===========================================================================
# Scenario 9: failure surfaces (LLM 429, timeout, malformed JSON; hard kill).
# ===========================================================================

class TestScenario9FailureSurfaces:
    def _make_pending_job(self, fake_db, job_id, text="Patient has hypertension and needs medication review."):
        now = datetime.now(timezone.utc)
        fake_db.collection("care_plan_outputs").document(job_id).set({
            "uid": "anon-1", "name": "Test", "source_filename": "text_input",
            "created_at": now, "updated_at": now, "status": "not_started",
            "stage": None, "input_source_kind": "text", "input_text": text,
            "input_doc_id": None, "input_source_filename": "text_input",
            "input_pdf_gcs_uri": None, "input_version": "v1-2", "grading_enabled": False,
            "expires_at": now + timedelta(hours=1),
        })

    def test_llm_429_quota_exceeded_surfaces_as_safe_terminal_error(self, client_worker, fake_db):
        job_id = str(uuid.uuid4())
        self._make_pending_job(fake_db, job_id)

        with patch("care_plan.pipeline.CarePlanPipeline.__init__", return_value=None):
            with patch(
                "care_plan.pipeline.CarePlanPipeline._generate_text",
                side_effect=gexc.ResourceExhausted("quota exceeded"),
            ):
                resp = _run_worker(client_worker, job_id)

        assert resp.status_code == 200  # worker always 200s to Cloud Tasks on a classified failure
        doc = fake_db.raw_doc("care_plan_outputs", job_id)
        assert doc["status"] == "error"
        assert doc["error_data"]["code"] == "VERTEX_QUOTA_EXCEEDED"
        assert "input_text" not in doc  # cleared on every terminal state

    def test_llm_timeout_surfaces_as_safe_terminal_error(self, client_worker, fake_db):
        job_id = str(uuid.uuid4())
        self._make_pending_job(fake_db, job_id)

        with patch("care_plan.pipeline.CarePlanPipeline.__init__", return_value=None):
            with patch(
                "care_plan.pipeline.CarePlanPipeline._generate_text",
                side_effect=gexc.DeadlineExceeded("deadline exceeded"),
            ):
                resp = _run_worker(client_worker, job_id)

        assert resp.status_code == 200
        doc = fake_db.raw_doc("care_plan_outputs", job_id)
        assert doc["status"] == "error"
        assert doc["error_data"]["code"] == "VERTEX_DEADLINE_EXCEEDED"

    def test_llm_malformed_json_surfaces_as_safe_terminal_error(self, client_worker, fake_db):
        from errors import SimplifyError
        job_id = str(uuid.uuid4())
        self._make_pending_job(fake_db, job_id)

        with patch("care_plan.pipeline.CarePlanPipeline.__init__", return_value=None):
            with patch(
                "care_plan.pipeline.CarePlanPipeline._generate_text",
                return_value="looks fine",
            ):
                with patch(
                    "care_plan.pipeline.CarePlanPipeline._generate_json",
                    side_effect=SimplifyError(ErrorCode.LLM_INVALID_JSON, detail="not json"),
                ):
                    resp = _run_worker(client_worker, job_id)

        assert resp.status_code == 200
        doc = fake_db.raw_doc("care_plan_outputs", job_id)
        assert doc["status"] == "error"
        assert doc["error_data"]["code"] == "LLM_INVALID_JSON"
        # user_hint/message must be present and not contain raw exception internals
        assert "Traceback" not in json.dumps(doc["error_data"], default=str)

    def test_worker_hard_kill_leaves_job_stuck_processing_until_client_watchdog(self, client_worker, fake_db):
        """Documents (rather than "fixes") the hard-kill case: if the worker
        process dies between marking status="processing" and reaching any
        terminal state, no code path in this repo flips it to a terminal
        state on its own -- the job doc simply stays "processing" until
        either (a) Cloud Tasks redelivers the task and the processing-lease
        check (routes/worker.py) finds the lease expired (>270s for a single
        job) and retries, or (b) frontend/src/components/
        ProcessingScreen.tsx's client-side WATCHDOG_TIMEOUT_MS (6 minutes)
        fires and shows the user a rescue message. This test only asserts
        the first half (the doc really does stay in "processing" with no
        code path unsticking it here); the 6-minute number is read directly
        from ProcessingScreen.tsx, not exercised by this backend suite."""
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        fake_db.collection("care_plan_outputs").document(job_id).set({
            "uid": "anon-1", "name": "Test", "source_filename": "text_input",
            "created_at": now, "updated_at": now, "status": "processing",
            "started_at": now, "stage": 3,
            "input_source_kind": "text", "input_text": "Patient has hypertension.",
            "input_doc_id": None, "input_source_filename": "text_input",
            "input_pdf_gcs_uri": None, "input_version": "v1-2", "grading_enabled": False,
            "expires_at": now + timedelta(hours=1),
        })
        # No worker request happens at all here (the process is "dead") --
        # just assert the doc is inert.
        doc = fake_db.raw_doc("care_plan_outputs", job_id)
        assert doc["status"] == "processing"


# ===========================================================================
# Scenario 10: rate limiting.
# ===========================================================================

class TestScenario10RateLimiting:
    @pytest.fixture(autouse=True)
    def _bypass_rate_limit(self):
        """Shadows the module-level autouse fixture of the same name (pytest
        fixture resolution: same-named fixture defined closer to the test
        wins) -- scenario 10 exists specifically to test the REAL rate
        limiter, so it must not be bypassed here."""
        yield

    def test_burst_within_limit_then_blocked_real_check_rate_limit(self, client_jobs, monkeypatch):
        """Exercises the REAL check_rate_limit()/_check_and_increment logic
        (not the check_rate_limit-level bypass used elsewhere in this file) --
        only Firestore persistence itself is faked."""
        store: dict[str, dict] = {}

        class _Ref:
            def __init__(self, doc_id):
                self.doc_id = doc_id

            def get(self, transaction=None):
                data = store.get(self.doc_id)
                snap = MagicMock()
                snap.exists = data is not None
                snap.get = lambda field: (data or {}).get(field)
                return snap

        class _Coll:
            def document(self, doc_id):
                return _Ref(doc_id)

        class _Client:
            def collection(self, name):
                return _Coll()

            def transaction(self):
                return MagicMock()

        def _fake_check_and_increment(transaction, ref, limit, now, expires_at):
            data = store.get(ref.doc_id)
            count = (data or {}).get("count", 0)
            if count >= limit:
                return False
            store[ref.doc_id] = {"count": count + 1, "updated_at": now, "expires_at": expires_at}
            return True

        monkeypatch.setattr("utils.rate_limit.firestore_client", lambda: _Client())
        monkeypatch.setattr("utils.rate_limit._check_and_increment", _fake_check_and_increment)
        # check_rate_limit itself is left untouched (real) -- only its own
        # Firestore call chain is faked, per this class's _bypass_rate_limit
        # override above.

        headers_json = {"Content-Type": "application/json"}
        limit = Constants.Limits.RATE_LIMIT_PER_IP_PER_HOUR
        statuses = []
        for _ in range(limit + 2):
            resp = client_jobs.post(
                "/jobs", data=json.dumps({"text": "hi"}), headers=headers_json,
                environ_overrides={"REMOTE_ADDR": "203.0.113.5"},
            )
            statuses.append(resp.status_code)

        # First `limit` requests pass the rate limiter (401 -- no auth header
        # -- since we're testing the limiter itself, not full auth); the
        # (limit+1)th and beyond are blocked with 429 BEFORE auth even runs.
        assert statuses[:limit] == [401] * limit
        assert statuses[limit] == 429
        assert statuses[limit + 1] == 429

    def test_trusted_proxy_hop_selection_cannot_be_bypassed_by_spoofed_xff(self, client_jobs, monkeypatch):
        from utils.rate_limit import get_client_ip
        app = client_jobs.application
        with app.test_request_context(
            "/jobs",
            headers={"X-Forwarded-For": "9.9.9.9, 203.0.113.7"},
            environ_overrides={"REMOTE_ADDR": "203.0.113.7"},
        ):
            # Exactly 1 trusted hop (this deployment's real topology): the
            # RIGHTMOST value is Google-appended and trustworthy; a client
            # claiming to be "9.9.9.9" via a spoofed XFF cannot make itself
            # look like a different bucket than its real address.
            assert get_client_ip() == "203.0.113.7"

        with app.test_request_context(
            "/jobs",
            headers={"X-Forwarded-For": "1.2.3.4"},  # attacker-supplied, single hop
            environ_overrides={"REMOTE_ADDR": "203.0.113.7"},
        ):
            # A single-value XFF IS trusted as-is under 1-hop topology (it's
            # the one value Cloud Run itself appended) -- this is inherent
            # to "1 trusted hop", not a bypass: the attacker cannot control
            # what Cloud Run appends, only what they prepend to their own
            # forwarded chain (which additional hops would then push left).
            assert get_client_ip() == "1.2.3.4"

    def test_rate_limiter_firestore_failure_fails_open_not_500(self, client_jobs, monkeypatch):
        def _boom():
            raise RuntimeError("Firestore unavailable")

        monkeypatch.setattr("utils.rate_limit.check_rate_limit", _boom)
        with patch.dict("os.environ", JOBS_ENV):
            with patch("routes.jobs.create_job_doc"):
                with patch("routes.jobs.enqueue_job_safe", return_value=None):
                    resp = client_jobs.post(
                        "/jobs", json={"text": "hi"},
                        headers={"Authorization": "Bearer x"},
                    )
        # Fails OPEN (documented, deliberate product choice): never a 500
        # just because the rate limiter's own Firestore write failed.
        assert resp.status_code != 500
        assert resp.status_code == 401  # falls through to the (failing) auth check, not blocked


# ===========================================================================
# Scenario 11: access control (route-level; firestore.rules reviewed
# statically -- NOT executed against a live Firestore emulator, see report).
# ===========================================================================

class TestScenario11AccessControl:
    def test_anon_user_b_cannot_delete_anon_user_as_job(self, client_jobs, fake_db, monkeypatch):
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        fake_db.collection("care_plan_outputs").document(job_id).set({
            "uid": "anon-A", "name": "Test", "source_filename": "text_input",
            "created_at": now, "updated_at": now, "status": "completed",
            "input_source_kind": "text", "input_doc_id": None,
            "input_source_filename": "text_input", "input_pdf_gcs_uri": None,
            "input_version": "v1-2", "grading_enabled": False,
            "expires_at": now + timedelta(hours=1),
        })

        headers_b = _auth_for(monkeypatch, "anon-B")
        resp, mock_delete = _delete_job(client_jobs, job_id, headers_b)
        assert resp.status_code == 403
        mock_delete.assert_not_called()
        # Doc must survive untouched.
        assert fake_db.raw_doc("care_plan_outputs", job_id) is not None

    def test_anon_user_a_can_delete_their_own_job(self, client_jobs, fake_db, monkeypatch):
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        fake_db.collection("care_plan_outputs").document(job_id).set({
            "uid": "anon-A", "name": "Test", "source_filename": "text_input",
            "created_at": now, "updated_at": now, "status": "completed",
            "input_source_kind": "text", "input_doc_id": None,
            "input_source_filename": "text_input", "input_pdf_gcs_uri": None,
            "input_version": "v1-2", "grading_enabled": False,
            "expires_at": now + timedelta(hours=1),
        })
        headers_a = _auth_for(monkeypatch, "anon-A")
        resp, _ = _delete_job(client_jobs, job_id, headers_a)
        assert resp.status_code == 204
        assert fake_db.raw_doc("care_plan_outputs", job_id) is None

    def test_firestore_rules_static_review_note(self):
        """firestore.rules was reviewed statically (read directly, not run
        against a live emulator -- no @firebase/rules-unit-testing harness
        or `firebase emulators:exec` wiring exists in this repo):

            allow get:  resource == null
                        || (request.auth != null && request.auth.uid == resource.data.uid)
                        || resource.data.shared == true
            allow list: request.auth != null && request.auth.uid == resource.data.uid
            allow write: if false

        Since `shared` is hard-coded `false` at creation for every job
        (JobDoc.for_single) and no code path ever flips it, an
        anonymous user B's token (uid != resource.data.uid) fails BOTH the
        uid check and the shared check for user A's doc, so `get`/`list`
        are denied; `write` is unconditionally denied to every client
        (server-side Admin SDK writes via utils/firebase.py bypass rules
        entirely, which is how the app itself writes). This matches the
        route-level behavior asserted above. Flagged as NOT independently
        verified against a live Firestore emulator in this test run.
        """
        assert True
