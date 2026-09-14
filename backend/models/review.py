"""Reviewer output + correction vocabulary shared with the corrector
(PRD 05 §4). Pipeline-internal only -- same posture as models.ledger."""

from __future__ import annotations

from typing import Literal

from .base import JsonModel

CorrectionOp = Literal["correct", "not_stated", "remove"]   # the whole vocabulary


class Correction(JsonModel):
    """One field-level finding. `path` addresses the assembled CarePlan
    (§4.2) -- the machine-readable contract the corrector consumes."""
    op: CorrectionOp
    path: str
    value: str | None = None   # required for "correct"; absent otherwise


class CoverageEntry(JsonModel):
    """One line of the enumerate-then-check-presence walk (brief §3.5) --
    answered for EVERY fact_id, not just ones judged missing."""
    fact_id: int
    present: bool


class ReviewResult(JsonModel):
    """`verdict` is informational only (§4.5) -- whether to run the
    corrector is decided from `len(corrections) > 0`."""
    verdict: Literal["pass", "needs_correction"]
    corrections: list[Correction] = []
    coverage: list[CoverageEntry] = []
