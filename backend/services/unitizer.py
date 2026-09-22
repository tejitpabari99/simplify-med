"""services/unitizer.py -- the deterministic unitizer (brainstorm.v1.md
§3.2): turns already-extracted text plus its SourceSpan provenance into a
numbered list[Unit], the only thing the grounding LLM call (03) ever
cites.

Pure, deterministic, and network-free by construction -- the same (text,
provenance) pair always produces an identical unit list, which is what
makes evidence citation by integer id reproducible (brief §3.2: "the
model cites one integer... file and page are recovered by lookup").
"""
from __future__ import annotations

import logging
from collections import Counter

from models.ledger import Unit
from models.provenance import SourceSpan

logger = logging.getLogger(__name__)


def unitize(text: str, provenance: list[SourceSpan]) -> list[Unit]:
    """Split `text` into Units using the (file, page, start_line, end_line)
    boundaries in `provenance`.

    `provenance` must be in document order, and its spans' line ranges
    must partition [0, len(text.split("\\n"))) with no gaps or overlaps --
    guaranteed by construction when `provenance` comes from
    resolve_uploaded_files or provenance_for_pasted_text (see their
    docstrings and tests/services/test_unitizer.py). This function does
    NOT re-validate that invariant on the hot path; a span whose range
    runs past the end of `text`'s lines is handled defensively (the loop
    below simply stops early) rather than raising, matching this
    codebase's existing "belt-and-suspenders, don't crash the request"
    posture elsewhere in the input path.

    Blank/whitespace-only lines are dropped silently -- no Unit is created
    for them -- but they still occupy a slot in the global line count, so
    `Unit.line` (1-indexed, reset at each span) matches what a human
    counting lines in the original page/file would call that line.
    `Unit.id` is assigned only to emitted (non-blank) units, sequentially
    starting at 1, in (span order, then line order within a span) -- i.e.
    document reading order. Same (text, provenance) in -> same list[Unit]
    out, every time (unit IDs are stable and reproducible; see PRD 02 §7).

    Logs one INFO-level aggregate of `extraction_method` counts across the
    emitted units before returning -- log-only, never affects the returned
    list.
    """
    lines = text.split("\n")
    units: list[Unit] = []
    next_id = 1
    for span in provenance:
        for offset, global_idx in enumerate(range(span.start_line, span.end_line + 1)):
            if global_idx >= len(lines):
                break  # defensive: malformed provenance: stop rather than crash
            line_text = lines[global_idx]
            if not line_text.strip():
                continue
            units.append(Unit(
                id=next_id,
                file=span.file,
                page=span.page,
                line=offset + 1,
                text=line_text,
                extraction_method=span.extraction_method,
            ))
            next_id += 1
    _log_extraction_signal(units)
    return units


def _log_extraction_signal(units: list[Unit]) -> None:
    """One INFO-level, per-run aggregate of how many units rest on which
    extraction method -- the earliest point this is fully known, before
    grounding (or any LLM call) has run at all. Log-only (PRD 12 SS3): does
    not affect `units` or anything downstream. No-op for an empty list
    (a job with zero units never reaches grounding anyway -- routes/
    worker.py's own MIN_MEANINGFUL_CONTENT_CHARS floor fails it first --
    so an aggregate over zero units would be pure noise, not signal)."""
    if not units:
        return
    counts = Counter(u.extraction_method for u in units)
    total = len(units)
    ocr = counts.get("ocr", 0)
    logger.info(
        "unitize: %d units (native=%d, ocr=%d, pasted=%d)",
        total, counts.get("native", 0), ocr, counts.get("pasted", 0),
        extra={"extraction_signal": {
            "total": total,
            "native": counts.get("native", 0),
            "ocr": ocr,
            "pasted": counts.get("pasted", 0),
            "ocr_rate": ocr / total,
        }},
    )


def provenance_for_pasted_text(text: str, *, file: str = "text_input") -> list[SourceSpan]:
    """Build the single-span provenance for pasted text (routes/jobs.py's
    text path -- no file at all, PRD 02 §4.2). `file="text_input"` matches
    the existing sentinel filename already used for pasted-text jobs
    (routes/jobs.py's input_source_filename, and utils.misc.
    derive_output_name's special-cased skip for that exact string) --
    reusing it means no new sentinel convention to keep in sync.

    Returns [] for empty text (no lines to span), consistent with an
    upload path that contributes no spans for a file with no usable text.
    """
    if not text:
        return []
    line_count = len(text.split("\n"))
    return [SourceSpan(
        file=file, page=1, start_line=0, end_line=line_count - 1,
        extraction_method="pasted",
    )]
