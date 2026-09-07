"""Base classes for strict JSON-serializable Pydantic models."""

from __future__ import annotations

from typing import Type, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T", bound="JsonModel")


class JsonModel(BaseModel):
    """Strict Pydantic base for all backend models."""

    model_config = ConfigDict(extra="forbid")

    def to_dict(self) -> dict:
        """Convert the model to a JSON-native dictionary."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls: Type[T], data: dict) -> T:
        """Validate a dictionary into this model class."""
        return cls.model_validate(data)
