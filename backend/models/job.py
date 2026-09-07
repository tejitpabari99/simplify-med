"""Typed Pydantic model for the Firestore care_plan_outputs job document."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import ConfigDict, Field

from .base import JsonModel
from .api_response import ErrorDetail, StatusEnum
from .care_plan.envelope import CarePlanInternal
from utils.constants import Constants

SourceKind = Constants.Uploads.SourceKind


class JobDoc(JsonModel):
    """Typed representation of a Firestore care_plan_outputs job document.

    Field names are the exact Firestore wire keys — do NOT rename without
    coordinating with the frontend and Firestore security rules.

    extra="ignore" is intentional: unknown keys written to Firestore
    out-of-band are silently dropped rather than raising ValidationError.
    """

    model_config = ConfigDict(extra="ignore")

    # ── Identity ──────────────────────────────────────────────────────────
    uid: str
    name: str
    source_filename: str

    # ── Timestamps ────────────────────────────────────────────────────────
    created_at: datetime
    updated_at: datetime

    # ── Lifecycle ─────────────────────────────────────────────────────────
    status: StatusEnum = StatusEnum.not_started
    stage: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    output_data: Optional[CarePlanInternal] = None
    error_data: Optional[ErrorDetail] = None

    # ── Input provenance ──────────────────────────────────────────────────
    input_source_kind: SourceKind
    input_text: Optional[str] = None
    input_source_filename: str
    input_pdf_gcs_uri: Optional[str] = None
    input_version: str = "v1-2"
    grading_enabled: bool = False

    # ── Single-job-only extras ────────────────────────────────────────────
    shared: Optional[bool] = None
    trace_id: Optional[str] = None

    # ── Expiry ────────────────────────────────────────────────────────────
    expires_at: Optional[datetime] = None
    # Filenames from a tolerant multi-file upload that were individually
    # unusable (corrupt/encrypted/blank/unsupported) and skipped rather than
    # aborting the whole batch -- see services.care_plan_input.
    # resolve_uploaded_files's tolerate_unusable_files param and
    # models.input.ResolvedInput.skipped_files. This field lets the client
    # show the user which of their uploaded files were skipped. Always []
    # when there were no skipped files.
    skipped_files: list[str] = Field(default_factory=list)

    # ── Factories ─────────────────────────────────────────────────────────

    @classmethod
    def for_single(
        cls,
        *,
        user_id: str,
        now: datetime,
        trace_id: Optional[str],
        input_fields: dict,
        expires_at: Optional[datetime] = None,
    ) -> "JobDoc":
        """Build a job doc for a care-plan job.

        input_fields dict must contain:
          input_source_kind, input_text, input_source_filename,
          input_pdf_gcs_uri, input_version, grading_enabled
        """
        return cls(
            uid=user_id,
            name=now.strftime("%b %d, %Y %H:%M"),
            source_filename=input_fields["input_source_filename"],
            created_at=now,
            updated_at=now,
            status=StatusEnum.not_started,
            shared=False,
            trace_id=trace_id,
            expires_at=expires_at,
            **input_fields,
        )

    # ── Persistence ───────────────────────────────────────────────────────

    def to_firestore(self) -> dict:
        """Serialise to a Firestore-ready dict (datetime objects preserved)."""
        return self.model_dump(mode="python", exclude_none=False)

    @classmethod
    def from_firestore(cls, data: dict) -> "JobDoc":
        """Parse a raw Firestore document dict into a typed JobDoc."""
        return cls.model_validate(data)
