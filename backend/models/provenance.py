"""Pydantic models for the deterministic per-(file, page) line-range map
and its GCS transport payload.

SourceSpan is the compact, GCS-persisted half of the provenance design: the
API computes it once, at job-creation time, from each uploaded file's own
extracted, page-segmented text. The worker later reconstructs the full,
larger list[Unit] (models.ledger.Unit) from the document text and spans via
services.unitizer.unitize, without ever re-touching original file bytes.

A SourceSpan never appears in any API response -- like Unit and Fact, it
is pipeline-/job-internal only. Unlike Unit and Fact, it is persisted in the
GCS payload, where it stays small by carrying a line range rather than a copy
of the text in that range.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import JsonModel

ExtractionMethod = Literal["native", "ocr", "pasted"]


class SourceSpan(JsonModel):
    """One contiguous, 0-indexed, inclusive range of global line indices --
    into the combined document's ``split("\\n")`` result -- attributed to
    one (file, page).

    Spans are produced in document order and, taken together, partition
    every line of the job's combined document with no gaps or overlaps.
    The two producers (services.care_plan_input.resolve_uploaded_files and
    services.unitizer.provenance_for_pasted_text) are responsible for this
    invariant; services.unitizer.unitize (the consumer) trusts it rather
    than re-validating it on the hot path -- see that function's docstring.
    """

    file: str
    page: int
    start_line: int
    end_line: int
    extraction_method: ExtractionMethod
    """How this span's text was produced -- "native" (PyPDF2/python-docx/
    BeautifulSoup/plain decode), "ocr" (Gemini vision transcription of an
    image, utils.image_ocr.extract_text_from_image), or "pasted" (typed or
    pasted directly by the user, no extraction step at all). A TRIAGE tag,
    not a confidence score (PRD 12 SS1): it records how the text was
    produced, never whether that production was accurate. Granularity is
    effectively per-file today (PRD 12 SS4.2 -- no per-page OCR fallback
    exists for PDFs), but lives on the per-(file, page) SourceSpan rather
    than a new per-file structure so a future per-page fallback would not
    require another schema change."""


class JobInputPayload(JsonModel):
    """Wire shape of the GCS object services.care_plan_input.upload_job_input
    writes and load_job_input reads back. It carries the document text and
    provenance map from the API to the worker as one payload because
    services.unitizer.unitize always consumes both together.

    Like SourceSpan, this model IS written to a persistence layer (a GCS
    object, not Firestore) -- unlike Unit/Fact, which never touch storage
    at all. Unlike SourceSpan, it never appears as a JobDoc field; it is
    the object input_payload_gcs_uri points AT, not a value stored inline.
    """

    text: str
    provenance: list[SourceSpan] = Field(default_factory=list)
