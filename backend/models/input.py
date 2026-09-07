"""Input model capturing the source of a pipeline run request."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import JsonModel
from utils.constants import Constants


INPUT_VERSION = Constants.Schema.INPUT_VERSION


class TextInput(JsonModel):
    mode: Literal["text"] = "text"
    text: str | None = None


Input = TextInput


class ResolvedInput(JsonModel):
    """Structured representation of a resolved pipeline input.

    Built in route helpers before the pipeline is invoked; carries the extracted
    text, metadata about the source, and (for file inputs) the size in bytes of
    the merged PDF that was produced and uploaded to GCS.

    combined_pdf_size stores the byte count of the merged PDF as a float for
    observability. The raw bytes are uploaded to GCS by the caller before this
    object is constructed; this model never holds binary data directly.
    """

    text: str
    source_description: str
    source_filename: str
    combined_pdf_size: float | None = None
    source_kind: str = "upload"
    file_count: int = 0
    file_types: list[str] = Field(default_factory=list)
    # Filenames excluded from `text` because they yielded no usable content
    # (e.g. a scanned/no-text-layer PDF, a corrupt/encrypted file). Only ever
    # non-empty when the caller opted into tolerant multi-file handling (see
    # services.care_plan_input.resolve_uploaded_files's
    # tolerate_unusable_files param).
    skipped_files: list[str] = Field(default_factory=list)
