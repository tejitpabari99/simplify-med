"""Tests for the provenance model: SourceSpan."""

import pytest
from pydantic import ValidationError

from models.provenance import JobInputPayload, SourceSpan


def _span(**overrides) -> SourceSpan:
    fields = dict(
        file="f.pdf", page=1, start_line=0, end_line=3, extraction_method="native"
    )
    fields.update(overrides)
    return SourceSpan(**fields)


def test_source_span_round_trips_through_dict():
    span = _span()

    assert SourceSpan.from_dict(span.to_dict()) == span


def test_source_span_rejects_unknown_field():
    with pytest.raises(ValidationError):
        SourceSpan(
            file="f",
            page=1,
            start_line=0,
            end_line=1,
            extraction_method="native",
            extra="x",
        )


def test_source_span_requires_extraction_method():
    with pytest.raises(ValidationError):
        SourceSpan(file="f", page=1, start_line=0, end_line=1)


def test_source_span_rejects_invalid_extraction_method():
    with pytest.raises(ValidationError):
        _span(extraction_method="scanned")


# Also exercises extraction_method's round-trip through JobInputPayload (via _span()).
def test_job_input_payload_round_trips_through_to_dict_from_dict():
    payload = JobInputPayload(
        text="Assessment:\n- Monitor blood pressure.\n- Follow up next week.",
        provenance=[
            _span(file="discharge.pdf", page=2, start_line=0, end_line=1),
            _span(file="labs.pdf", page=1, start_line=2, end_line=2),
        ],
    )

    assert JobInputPayload.from_dict(payload.to_dict()) == payload


def test_job_input_payload_rejects_unknown_key():
    with pytest.raises(ValidationError):
        JobInputPayload(text="x", provenance=[], extra="y")
