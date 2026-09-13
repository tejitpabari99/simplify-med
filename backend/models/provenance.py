"""Pydantic model for the deterministic per-(file, page) line-range map
persisted alongside a job's flattened input text.

SourceSpan is the compact, Firestore-persisted half of the provenance
design (PRD 02 §4.1): the API computes it once, at job-creation time, from
data only it has (each uploaded file's own extracted, page-segmented
text); the worker later reconstructs the full, larger list[Unit] (models.
ledger.Unit) from (input_text, list[SourceSpan]) via services.unitizer.
unitize, without ever re-touching original file bytes.

A SourceSpan never appears in any API response -- like Unit and Fact, it
is pipeline-/job-internal only. Unlike Unit and Fact, it IS persisted to
Firestore (as JobDoc.input_provenance), which is exactly why it stays
small: it carries a line RANGE, never a copy of the text in that range.
"""
from __future__ import annotations

from pydantic import Field

from .base import JsonModel


class SourceSpan(JsonModel):
    """One contiguous, 0-indexed, inclusive range of global line indices --
    into `input_text.split("\\n")` -- attributed to one (file, page).

    Spans are produced in document order and, taken together, partition
    every line of the job's combined input_text with no gaps or overlaps.
    The two producers (services.care_plan_input.resolve_uploaded_files and
    services.unitizer.provenance_for_pasted_text) are responsible for this
    invariant; services.unitizer.unitize (the consumer) trusts it rather
    than re-validating it on the hot path -- see that function's docstring.
    """

    file: str
    page: int
    start_line: int
    end_line: int


class JobInputPayload(JsonModel):
    """Wire shape of the GCS object services.care_plan_input.upload_job_input
    writes and load_job_input reads back -- the whole reason this object
    exists is to carry input_text and input_provenance from the API to the
    worker as one payload (PRD 09 §4.1), since the one function that ever
    consumes either (services.unitizer.unitize) always consumes both.

    Like SourceSpan, this model IS written to a persistence layer (a GCS
    object, not Firestore) -- unlike Unit/Fact, which never touch storage
    at all. Unlike SourceSpan, it never appears as a JobDoc field; it is
    the object input_payload_gcs_uri points AT, not a value stored inline.
    """

    text: str
    provenance: list[SourceSpan] = Field(default_factory=list)
