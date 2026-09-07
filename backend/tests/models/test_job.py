"""Unit tests for models.job.JobDoc."""
import pytest
from datetime import datetime, timezone

from models.job import JobDoc
from models.api_response import StatusEnum, ErrorDetail


def test_import():
    from models.job import JobDoc  # noqa: F401


@pytest.fixture
def now():
    return datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def input_fields():
    return {
        "input_source_kind": "text",
        "input_text": "hello",
        "input_source_filename": "note.txt",
        "input_pdf_gcs_uri": None,
        "input_version": "v1-2",
        "grading_enabled": False,
    }


def test_for_single_sets_shared_trace(now, input_fields):
    job = JobDoc.for_single(user_id="u2", now=now, trace_id="abc123", input_fields=input_fields)
    assert job.shared is False
    assert job.trace_id == "abc123"
    assert job.status == StatusEnum.not_started


def test_for_single_defaults_expires_at_none(now, input_fields):
    job = JobDoc.for_single(user_id="u2", now=now, trace_id=None, input_fields=input_fields)
    assert job.expires_at is None


def test_for_single_accepts_expires_at_kwarg(now, input_fields):
    from datetime import timedelta
    expires = now + timedelta(hours=1)
    input_fields = {**input_fields, "grading_enabled": True}
    job = JobDoc.for_single(
        user_id="u2", now=now, trace_id=None, input_fields=input_fields,
        expires_at=expires,
    )
    assert job.expires_at == expires


def test_to_firestore_writes_explicit_null_expires_at_when_not_set(now, input_fields):
    job = JobDoc.for_single(user_id="u2", now=now, trace_id=None, input_fields=input_fields)
    d = job.to_firestore()
    assert "expires_at" in d
    assert d["expires_at"] is None


def test_to_firestore_returns_datetime_objects(now, input_fields):
    job = JobDoc.for_single(user_id="u2", now=now, trace_id=None, input_fields=input_fields)
    d = job.to_firestore()
    assert isinstance(d["created_at"], datetime)
    assert isinstance(d["updated_at"], datetime)
    assert "status" in d


def test_from_firestore_roundtrip(now, input_fields):
    job = JobDoc.for_single(user_id="u2", now=now, trace_id=None, input_fields=input_fields)
    d = job.to_firestore()
    job2 = JobDoc.from_firestore(d)
    assert job2.uid == job.uid
    assert job2.input_text == job.input_text
    assert job2.created_at == job.created_at


def test_from_firestore_ignores_extra_field(now, input_fields):
    d = JobDoc.for_single(user_id="u2", now=now, trace_id=None, input_fields=input_fields).to_firestore()
    d["unexpected_field"] = "surprise"
    job2 = JobDoc.from_firestore(d)
    assert not hasattr(job2, "unexpected_field")


def test_error_data_typed_submodel(now, input_fields):
    from errors import ErrorCode, build_error_data
    err = build_error_data(ErrorCode.UNKNOWN_ERROR, "boom")
    d = JobDoc.for_single(user_id="u2", now=now, trace_id=None, input_fields=input_fields).to_firestore()
    d["error_data"] = err
    job = JobDoc.from_firestore(d)
    assert isinstance(job.error_data, ErrorDetail)
    assert job.error_data.code == err["code"]
    assert job.error_data.message == err["message"]
    out_d = job.to_firestore()
    assert isinstance(out_d["error_data"], dict)
    assert "code" in out_d["error_data"]
    assert "message" in out_d["error_data"]
    assert "timestamp" in out_d["error_data"]


def _make_care_plan_internal():
    """Build a minimal CarePlanInternal for test use."""
    from models.care_plan.envelope import CarePlanInternal
    from models.care_plan.care_plan import CarePlan
    from models.grading import Grading
    from models.input import TextInput
    from models.metrics import Metrics

    metrics = Metrics(
        session_id="session-1",
        pipeline_version="v1-2",
        input_type="text",
        created_at="2026-01-15T10:00:00+00:00",
    )
    care_plan = CarePlan(
        summary="Take blood pressure medicine daily.",
        terms={
            "hypertension": {
                "definition": "High blood pressure.",
                "source": "provider note",
            }
        },
    )
    return CarePlanInternal(
        metrics=metrics,
        input=TextInput(text="Patient note"),
        grading=Grading(),
        care_plan=care_plan,
    )


def test_output_data_typed_submodel(now, input_fields):
    from models.care_plan.envelope import CarePlanInternal

    cpi = _make_care_plan_internal()
    out = cpi.to_dict()

    d = JobDoc.for_single(user_id="u2", now=now, trace_id=None, input_fields=input_fields).to_firestore()
    d["output_data"] = out
    job = JobDoc.from_firestore(d)
    assert isinstance(job.output_data, CarePlanInternal)
    out_d = job.to_firestore()
    assert isinstance(out_d["output_data"], dict)


def test_status_enum_default(now, input_fields):
    job = JobDoc.for_single(user_id="u2", now=now, trace_id=None, input_fields=input_fields)
    assert job.status == StatusEnum.not_started


def test_input_source_kind_rejects_unknown_value(now, input_fields):
    bad_fields = {**input_fields, "input_source_kind": "something_else"}
    with pytest.raises(Exception):
        JobDoc.for_single(user_id="u2", now=now, trace_id=None, input_fields=bad_fields)


def test_input_source_kind_accepts_upload(now, input_fields):
    upload_fields = {**input_fields, "input_source_kind": "upload"}
    job = JobDoc.for_single(user_id="u2", now=now, trace_id=None, input_fields=upload_fields)
    assert job.input_source_kind == "upload"
