"""Tests for the provenance model: SourceSpan."""

import pytest
from pydantic import ValidationError

from models.provenance import SourceSpan


def _span(**overrides) -> SourceSpan:
    fields = dict(file="f.pdf", page=1, start_line=0, end_line=3)
    fields.update(overrides)
    return SourceSpan(**fields)


def test_source_span_round_trips_through_dict():
    span = _span()

    assert SourceSpan.from_dict(span.to_dict()) == span


def test_source_span_rejects_unknown_field():
    with pytest.raises(ValidationError):
        SourceSpan(file="f", page=1, start_line=0, end_line=1, extra="x")
