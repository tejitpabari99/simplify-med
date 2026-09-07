"""Tests for the strict Pydantic model base."""

import importlib

import pytest
from pydantic import ValidationError

from models.base import JsonModel


class SimpleModel(JsonModel):
    name: str
    value: int


def test_json_model_forbids_extra_kwargs():
    with pytest.raises(ValidationError):
        SimpleModel(name="test", value=42, unexpected=True)


def test_json_model_to_dict_uses_json_mode_for_serialization():
    original = SimpleModel(name="test", value=42)

    assert original.to_dict() == {"name": "test", "value": 42}
    assert SimpleModel.from_dict(original.to_dict()) == original


def test_import_models_base_succeeds_without_legacy_references():
    module = importlib.import_module("models.base")

    assert module.JsonModel is JsonModel
    assert not hasattr(module, "VersionedModel")
    assert not hasattr(module, "VersionedJsonModel")
    assert "dataclasses" not in module.__dict__
    assert "typing" not in module.__dict__
