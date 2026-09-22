"""Pydantic models for the deterministic unitizer and the grounding ledger.

Unit: one deterministically-numbered span of source text, produced by the
unitizer (see PRD 02) before any LLM call runs. The grounding step (03)
cites a Unit only by its integer `id` — `file` and `page` are recovered by
lookup against the unit list, never asked of the model, and therefore
cannot be hallucinated (brief brainstorm.v1.md §3.2).

Fact: one atomic, evidence-linked clinical statement, emitted by the
grounding LLM call (03) as a flat ledger, at roughly clause granularity
(brief §2.5, "one fact per note clause, not one fact per attribute").
Stores a POINTER into its cited unit's text (`char_start`/`char_end`),
not a copy — the LLM's own verbatim quote is verified by 03 and then
discarded in favor of its location; call `quote_for(fact, units_by_id)`
below to rehydrate it. Consumed by assembly (04) and review (05), both of
which must use `quote_for()` rather than a `Fact.quote` field, which does
not exist. Never persisted to Firestore and never sent to the frontend —
pipeline-internal only (brief §3.10).
"""

from __future__ import annotations

from typing import Literal

from .base import JsonModel

# The eight categories the grounding step is prompted with (brief §3.3).
# Deliberately spelled identically to the matching CarePlan field names
# (reason_for_visit, diagnosis, medications, tests, procedures, other,
# follow_up, warning_signs) so assembly's category -> CarePlan-field
# mapping is a direct lookup, not a translation table. "diagnosis" here
# corresponds to CarePlan.diagnosis.details specifically (see brief §3.3
# table row "diagnosis.details"); `low_priority` is deliberately absent —
# it's an assembly-time priority judgement, not something the grounder tags.
FactCategory = Literal[
    "reason_for_visit",
    "diagnosis",
    "medications",
    "tests",
    "procedures",
    "other",
    "follow_up",
    "warning_signs",
]


class Unit(JsonModel):
    """One deterministically-numbered span of source text. Built by the
    unitizer (02), never by an LLM. `id` is the only handle the grounding
    LLM ever sees or cites."""

    id: int
    file: str
    page: int
    line: int
    text: str


class Fact(JsonModel):
    """One atomic clinical statement extracted by grounding (03)."""

    id: int
    category: FactCategory
    unit_id: int
    char_start: int
    char_end: int
    text: str


def quote_for(fact: Fact, units_by_id: dict[int, Unit]) -> str:
    """Rehydrate the verbatim evidence quote for `fact` on demand from the
    in-memory unit list, rather than reading a `quote` field that does not
    exist on `Fact`. `char_start`/`char_end` are Python slice offsets into
    the cited unit's `text` -- `unit.text[char_start:char_end]` -- computed
    once by grounding's deterministic offset-recovery step (PRD 03 §4.3)
    and never re-derived here; this helper only performs the lookup and
    slice. Callers (04's assembly prompt, 05's corrector) must look the
    unit up by `fact.unit_id` (or reuse a `units_by_id` map they already
    have, e.g. `{u.id: u for u in units}`) and pass it in -- this module
    does not itself carry a reference to the current job's unit list."""
    return units_by_id[fact.unit_id].text[fact.char_start:fact.char_end]
