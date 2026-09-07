"""Tests for utils/job_helpers.py."""
from utils.job_helpers import canonical_input_type


def test_canonical_input_type_known_kinds():
    assert canonical_input_type("upload") == "file"
    assert canonical_input_type("text") == "text"


def test_canonical_input_type_unknown_kind_defaults_to_text():
    assert canonical_input_type("something_unrecognized") == "text"
