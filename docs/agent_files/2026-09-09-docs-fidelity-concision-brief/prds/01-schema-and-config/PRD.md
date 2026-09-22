# PRD 01 — Schema and Config

Parent brief: `docs/agent_files/2026-09-09-docs-fidelity-concision-brief/brainstorm.v1.md` (approved; not re-litigated here).
Branch: `docs/fidelity-concision-brief`.
Depends on: nothing (root of the decomposition). Depended on by: 02, 03, 04, 05, 06, 07, 08.

## 1. Problem

The current `CarePlan` Pydantic schema and its two supporting config surfaces (`firestore.rules`, CORS origins) encode the rewrite-then-extract architecture the brief replaces, and they actively cause the two defects the brief names:

- **Fabrication is baked into defaults.** `WarningSign.urgency` defaults to `"monitor"` and `CarePlan.urgency` defaults to `"normal"` — a warning sign or a whole visit the model never assessed reads as an affirmative, specific clinical judgement. `importance` defaults to `"low"` on five models for a field nothing downstream consumes.
- **Dead/unreachable fields carry real risk or real confusion.** `additional_info` has no prompt rule anywhere and is rendered under a fabricated "Data Sources" heading (`CarePlanView.tsx:348`, variable named `path`). `Constants.Enums.SOURCE` (`documents | recording | notes`) is unpopulated by any real distinction and `recording` refers to a feature (audio) that does not exist. `JobDoc.shared` is hard-coded `False` forever, and `firestore.rules:7`'s `|| resource.data.shared == true` clause is therefore unreachable — but it is live code, a latent hole if `shared` is ever set from anywhere.
- **The schema has no representation for the new pipeline's central artifact.** The inverted pipeline (ground → assemble+render → review → correct) needs a flat, evidence-linked fact ledger and a deterministic unit list. No such model exists.
- **The schema has no way to distinguish "already done" from "still to do."** Every actionable item type lacks a `status` field, which blocks the Next Steps redesign (08) that splits by status.
- **CORS origins are hardcoded**, which means every local ngrok test session (rotating free-tier URL) requires a source edit.

This PRD is the schema and config foundation every other sub-project builds on. Nothing here implements the pipeline, prompts, unitizer, grounding, review, correction, glossary, or frontend — it only settles the data contracts those sub-projects consume.

## 2. Goals

- Delete every schema field the brief identifies as a defaults-fabrication or dead-content risk: `CarePlan.additional_info`, `CarePlan.urgency`, `Diagnosis.main_conclusion`, `importance` (5 models), `source` (5 models) plus the `SOURCE` and `IMPORTANCE` enums.
- Make `WarningSign.urgency` nullable with no default, preserving it as an extracted (not derived) field.
- Add a required `status: Literal["to_do", "done"]` to the five actionable-item models.
- Fold `Medication.change` / `change_description` into one field.
- Give `CarePlan.summary` a citable set of fact IDs.
- Retire `RawArtifacts` / `CarePlan.raw` and settle what (if anything) replaces it as the pipeline's intermediate artifact.
- Define `Unit` and `Fact` as the settled contract between the unitizer (02), grounding (03), assembly (04), and review (05).
- Close the dead `firestore.rules` clause and settle whether `JobDoc.shared` should go with it.
- Make CORS origins configurable via `CORS_ALLOWED_ORIGINS` with production-identical defaults.
- Identify every test and fixture this breaks and specify what each should assert instead.

## 3. Non-Goals

- No prompt text (03, 04, 05, 07 own the prompts that populate these fields).
- No pipeline wiring — `care_plan/pipeline.py` and `services/care_plan_pipeline.py` keep calling the old three LLM steps until 06 rewires them. This PRD's job is only to make the target schema exist and compile; 06 is responsible for making the pipeline actually produce it.
- No unitizer implementation (02), no grounding/coverage-check logic (03), no assembly/render logic (04), no review/correction logic (05), no glossary curation (07).
- No frontend code changes. `frontend/src/types/carePlan.ts` is explicitly 08's file — this PRD only specifies the contract it must match (§6).
- No `Constants.Pipeline.PIPELINE_STEPS` changes. That enum's step members/labels belong to 06 (pipeline-orchestration owns re-sequencing GROUND/ASSEMBLE_RENDER/REVIEW/CORRECT). This PRD deletes `Constants.Enums.SOURCE`/`IMPORTANCE` only, which share the file but not the enum.
- No migration code, no `v1-3`, no dual-schema support, per the global constraint. `Constants.Schema.CARE_PLAN_VERSION` stays `"1.2"` — this is not a version bump, it's the same version mutated in place (consistent with "not live, no stored documents").
- No live-Firestore-emulator testing of `firestore.rules` (none exists in this repo today; out of scope to add).

## 4. Architecture Decisions

### 4.1 `backend/models/care_plan/care_plan.py`

Full old → new field table, model by model:

**`CarePlan`**

| Field | Old | New |
|---|---|---|
| `urgency` | `Literal["normal","caution","concern","urgent"] = "normal"` | **deleted** |
| `additional_info` | `list[str] = Field(default_factory=list)` | **deleted** |
| `summary` | `str = ""` | unchanged |
| `summary_fact_ids` | — | **added**: `list[int] = Field(default_factory=list)` — internal provenance, stripped before the API response (§4.1's internal-provenance-fields note) |
| `raw` | `RawArtifacts \| None = None` | **deleted** (see §4.1.4) |

**`Diagnosis`**

| Field | Old | New |
|---|---|---|
| `main_conclusion` | `str = ""` | **deleted** |
| `changed_since_last_visit`, `details` | unchanged | unchanged |

**`Medication`, `Test`, `Procedure`, `OtherInstruction`, `WarningSign`** (all five)

| Field | Old | New |
|---|---|---|
| `importance` | `Constants.Enums.IMPORTANCE = Constants.Enums.IMPORTANCE.LOW` | **deleted** |
| `source` | `Constants.Enums.SOURCE \| None = None` | **deleted** |

**`WarningSign.urgency`**

| Old | New |
|---|---|
| `Literal["emergency","call_doctor","monitor","normal_side_effect"] = "monitor"` | `Literal["emergency","call_doctor","monitor","normal_side_effect"] \| None` — **no default**. The field is now required to be present in every payload (nothing may silently omit it), but its value may legitimately be `null`. This is the same asymmetry the brief draws for `status` in reverse: omission is not allowed, but an honest "don't know" is. It mirrors `DiagnosisDetail.severity`'s nullability but deliberately does *not* copy its `= None` default — `severity` may be validly absent from a source that never discusses severity; `urgency` on a warning sign the model chose to extract at all should always get an explicit judgement call, even if that judgement is "the note doesn't say."

**`Medication`, `Test`, `Procedure`, `OtherInstruction`, `FollowUp`** — new required field:

```python
status: Literal["to_do", "done"]
```

No default (strict). `FollowUp` gets it too, per the brief's explicit list in §3.9/decision-log row 41 ("added and REQUIRED on Medication, Test, Procedure, OtherInstruction, FollowUp") even though `FollowUp` isn't named in prompt §D of the task brief's item list — the design brief's own schema-changes section (3.9) is unambiguous, and `FollowUp` is exactly the kind of actionable item ("go to your appointment") the status split (08) needs. Treating it as extracted-not-derived: a follow-up already attended is `"done"`.

**`Medication`, `Test`, `Procedure`, `OtherInstruction`, `FollowUp`, `WarningSign`** (all six) — new field:

```python
source_fact_ids: list[int] = Field(default_factory=list)
```

No default requirement beyond the empty list (matches `summary_fact_ids`'s own default). Populated by assembly (04) as it maps each `Fact` onto the item it becomes; consumed by review (05) to check every cited id exists in the ledger. See "Fact-ID citation fields" below for the full shape rationale and — the more consequential decision — why and where this field (and `summary_fact_ids`) must be stripped before it ever reaches an API response.

**`Medication.change` / `Medication.change_description` fold**

Old:
```python
change: bool = False
change_description: str = ""
```

New:
```python
change: str = ""
```

One field. `""` means "nothing noteworthy to report about a change" (the note doesn't flag this medication as new, stopped, or adjusted). Non-empty means the model wrote a plain-language description of what changed — `"Started today."`, `"Dose increased from 5 mg to 10 mg."`, `"Discontinued as of this visit."`. This matches every other informational string field on `Medication` (`why`, `instructions`, `side_effects_to_watch`, ...), all of which already default to `""` rather than being `Optional[str] = None` — so this fold is not a new idiom, it's applying the schema's existing idiom to a field that never should have been two fields. The old `bool` was redundant the moment `change_description` existed: a non-empty description already implies "yes, there's a change to report."

*Alternative considered and rejected*: keep two fields but make `change_description` required-if-`change`. Rejected because cross-field conditional-requirement validators are exactly the kind of complexity this fold is meant to remove, and because "torn" cases (the note is ambiguous about whether something changed) are better served by an empty string than by a forced boolean guess — consistent with the brief's "remove nothing, don't force inference" principle.

**Fact-ID citation fields: `summary_fact_ids` and `source_fact_ids`**

Two fact-ID citation fields exist in the new schema, both populated by assembly (04) and consumed by review (05). Together they are the schema-level half of the project's soundness contract (§9 — Change C): every care-plan item cites the facts it's built from, and review checks that every cited id actually exists in the ledger.

`CarePlan.summary` gets a sibling list field, not an object wrapper:

```python
summary: str = ""
summary_fact_ids: list[int] = Field(default_factory=list)
```

`Medication`, `Test`, `Procedure`, `OtherInstruction`, `FollowUp`, and `WarningSign` — the six item models a per-item citation makes sense on — each get the identical shape:

```python
source_fact_ids: list[int] = Field(default_factory=list)
```

(`Diagnosis`/`DiagnosisDetail` and `ReasonForVisit` do not get one — out of this decomposition's six-model list; `questions` and `low_priority` are plain `list[str]`, generated/judged rather than mapped 1:1 from a single fact, and are checked differently at review per brief §3.5.)

Rejected alternative for `summary_fact_ids`'s shape: making `summary` a small object (`{text: str, fact_ids: list[int]}`). Reasons to prefer the sibling-list shape, which by the same logic settles `source_fact_ids`'s shape too:
1. `summary` today is a plain string consumed directly by the frontend ("What You Need to Know" card body, and `buildPdfHtml.ts`). Keeping it a string means 08 does not have to touch how the summary itself is rendered — only how (or whether) it reads the new sibling field, which it doesn't need to for rendering at all (see §6). The same reasoning covers every item model gaining `source_fact_ids`: `title`, `why`, `instructions`, etc. stay exactly as 08 already renders them.
2. `CarePlan` already has multiple flat sibling relationships of exactly this shape (`reason_for_visit` is a list sibling of nothing else; `diagnosis` is an object *because* it has 2+ heterogeneous sub-fields — `summary`/each item doesn't gain anything from that pattern since it has exactly one piece of citation metadata).
3. Review (05) needs to check "each cited fact supports what this summary/item says, nothing uncited crept in" (brief §3.5) — a flat `list[int]` is the simplest possible input to that check; no need to reach into a nested object.
4. Neither field is ever rendered to the patient — the ledger and anything that cites into it are explicitly internal (brief §3.10) — so there is no UI reason to co-locate either with the text it cites.

**Both fields must never reach the API response, the frontend, or the PDF.** See the new subsection immediately below. This reverses an earlier draft of this PRD's reasoning for `summary_fact_ids` specifically, which held that it is "small (a handful of ints) and, unlike `raw`, is not being stripped before persistence for size reasons." That reasoning answered the wrong question — it was about Firestore document *size*, not about whether a fact-ID list is safe to expose. The owner's decision (extending brief §3.10's "the ledger is never displayed" to anything that cites into it) is that a fact-ID list is exactly as internal as the ledger it points into, regardless of how small it is; size was never the reason either field needs to be stripped.

**Internal provenance fields never reach the API boundary**

Unlike `CarePlan.raw` (see "`RawArtifacts` retirement" below), there is no existing stripping mechanism for `summary_fact_ids`/`source_fact_ids` to inherit, because neither field exists in the codebase today — this PRD is what introduces them. Verified by repo-wide grep: `summary_fact_ids` has zero hits anywhere in `backend/` as of this PRD, and `routes/worker.py`'s only pre-persistence stripping is the two explicit `.pop()` calls at `worker.py:202-203` (`care_plan.raw`, `input.text`) — there is no generic "strip internal-only fields" mechanism in this codebase to plug into; each stripped field is named by hand at that one call site.

**This is a gap this PRD must specify a fix for, not a mechanism that already generalizes.** The fix, to land alongside `raw`'s stripping at `routes/worker.py:195-203`:

```python
output_data.get("care_plan", {}).pop("raw", None)
output_data.get("input", {}).pop("text", None)
output_data.get("care_plan", {}).pop("summary_fact_ids", None)
for _key in ("medications", "tests", "procedures", "other", "follow_up", "warning_signs"):
    for _item in output_data.get("care_plan", {}).get(_key, []):
        _item.pop("source_fact_ids", None)
```

Seven fields (one top-level, six nested one-per-item-list) is enough repetition to warrant a small named helper rather than inline loops at the call site — recommended shape is a module-level `_strip_internal_provenance(care_plan_dict: dict) -> None` in `routes/worker.py` that mutates in place and is called once right where the two existing `.pop()` calls already live — but the exact factoring is an implementation call for whoever lands it. What this PRD fixes is *that* both fields must be stripped here, unconditionally, before `complete_job` persists `output_data` — not the helper's precise shape.

**This PRD specifies the fix but does not implement it — flagged for 06**, consistent with this PRD's existing precedent one section below (the dead `.pop("raw", None)` cleanup is likewise specified here and left for 06 to make, since `routes/worker.py` is 06's file to edit per this PRD's Non-Goals). It must land in the same change that makes 04 actually populate these fields with real fact ids (04 is what turns "declared but always `[]`" into "carries real citations"), since an unpopulated field has nothing to leak but a populated, un-stripped one is a live provenance leak the moment 04 exists. Recorded as `[RESOLVED]` in §9.

**`RawArtifacts` retirement**

```python
class RawArtifacts(JsonModel):
    text: str
    simplified_text: str
    clarified_text: str
```

**Decision: delete `RawArtifacts` and `CarePlan.raw` outright. Nothing replaces it on `CarePlan`.**

Rationale, verified against the actual code (`backend/routes/worker.py:195-199`):

```python
# Jobs are short-lived and the UI never reads raw text/simplified_text/
# clarified_text, nor the original input text — drop the whole (optional) `raw`
# key and the (optional) `input.text` key so completed docs stay well
# under Firestore's 1 MiB doc limit...
output_data.get("care_plan", {}).pop("raw", None)
```

`raw` was *already* always stripped before a job document is persisted or read by the frontend — it existed purely as pipeline-internal scratch space that happened to be threaded through the `CarePlan` Pydantic model. Two of its three fields (`simplified_text`, `clarified_text`) name pipeline stages (`simplify_language`, `clarify_and_action`) that no longer exist once the prose passes are deleted (brief §2.5, §3.4). There is nothing coherent left to rename it to on `CarePlan` itself.

The evidence ledger that *is* the new pipeline's intermediate artifact is explicitly **not displayed** (brief §3.10: "The evidence ledger is NOT displayed. It exists to make grounding and coverage checkable, not to show provenance to the patient.") and is deliberately outside the `CarePlan` schema family (brief decision-log row: "Grounding emits a FLAT ledger of atomic facts... Assembly into the typed CarePlan is a separate step"). Given `raw` never survived to storage anyway, putting the (larger, more sensitive — it's closer to verbatim source text) ledger where `raw` used to be would be a regression, not a preservation: it would put patient-identifying source excerpts one `.pop()`-removal-bug away from Firestore, inside a document type already flagged as tight against the 1 MiB limit.

**Where the ledger actually lives**: as pipeline-internal, non-Pydantic state, the same way `simplified`/`clarified`/`raw_text` already travel today — as fields on the plain `@dataclass` pipeline-event types (`models/pipeline_events.py`: `PipelineRunResult`, `AdapterResult`). These are not `JsonModel`s, are never serialized to Firestore, and are exactly the mechanism the current code already uses to pass non-persisted intermediate text between pipeline stages. **This PRD does not modify `pipeline_events.py`** — that file is 06's (pipeline-orchestration) to extend with `units: list[Unit]` / `ledger: list[Fact]` fields once 02/03 exist. It's called out here only so 06's author knows the intended shape and doesn't reach for `CarePlan.raw` (which won't exist) as the carrier.

**Downstream consequence flagged for 06**: `routes/worker.py:198`'s `output_data.get("care_plan", {}).pop("raw", None)` becomes dead code (a no-op pop of a key that will never be present) the moment this PRD lands. It is harmless as dead code (SOURCE:0 breakage — `.pop(key, None)` on an absent key is a no-op) but should be deleted by 06 when it rewires `routes/worker.py`, not left as a confusing no-op forever.

### 4.2 `backend/utils/constants.py`

```python
class Enums:
    class SOURCE(Enum):        # DELETE — whole nested class
        DOCUMENTS = "documents"
        RECORDING = "recording"
        NOTES     = "notes"

    class IMPORTANCE(Enum):    # DELETE — whole nested class
        HIGH = "high"
        LOW  = "low"
```

Verified via repo-wide grep: `Constants.Enums.SOURCE` and `Constants.Enums.IMPORTANCE` are referenced only from `backend/models/care_plan/care_plan.py` (10 call sites, all deleted by §4.1). Once both nested classes are gone, `class Enums:` itself has zero remaining members and zero remaining consumers — **delete the empty `Enums` container class too**, not just its contents. Leaving an empty, unused namespace class is exactly the kind of dead surface the brief's "mutate in place, no versioning cruft" constraint argues against.

`Constants.Pipeline.PIPELINE_STEPS` lives in the same file (`constants.py:63-79`) but is untouched by this PRD — it's 06's territory (see Non-Goals). Confirm no accidental collateral: `SOURCE`/`IMPORTANCE` and `PIPELINE_STEPS` are unrelated nested classes; deleting the former two does not touch the latter.

### 4.3 New module: `backend/models/ledger.py`

**Placement decision**: a new flat module directly under `backend/models/`, alongside `grading.py`, `input.py`, `metrics.py`, `job.py`, `pipeline_events.py` — **not** a new subpackage (unlike `care_plan/`, which is a package only because it already held two related files plus an `__init__.py` re-export surface). `Unit` and `Fact` are two small, related classes with no sub-package's worth of internal structure; the flat-module precedent fits better than inventing a new package for two classes.

**Why not inside `models/care_plan/`?** Because the ledger is explicitly *not* part of the `CarePlan` family (§4.1.4) — it is never nested inside a `CarePlan` instance, never serialized as part of `CarePlanInternal`, and never persisted. Co-locating it with `care_plan/*.py` would visually suggest a parent-child relationship the design deliberately does not have.

```python
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
```

Field-by-field rationale:

- **`Unit.id` / `Fact.id`** — both plain `int`. The brief's own diagram (§3.2) shows unit IDs as bare integers (`id: 47`); using the same type for `Fact.id` keeps both ledgers addressable the same way. `Fact.id` is **not spelled out explicitly** in the task's §B bullet list ("category tag, a unit/line ID, a verbatim quote, and the fact content") but is required by other parts of the same brief that this PRD must reconcile: `summary_fact_ids`/`source_fact_ids: list[int]` (§4.1) need something to point at, and every downstream citation check (04's assembly, 05's per-item soundness check) addresses facts by this id — which requires each fact to be individually addressable regardless of which direction the citation check runs. This is a filled gap, not a contradiction of the brief; recorded as `[RESOLVED]` in §9.
- **`Fact.unit_id`** — the brief's prose calls this "a line ID"; structurally it is `Unit.id` (the unitizer's numbering is the only numbering that exists — brief §3.2 explicitly retires per-page line-counting in favor of one flat `Unit.id` sequence). Named `unit_id` rather than `line_id` to avoid implying it's a raw text-file line number.
- **`Fact.char_start` / `Fact.char_end`** — `int`, Python slice offsets into the cited `Unit.text` (`unit.text[char_start:char_end]`). This replaces an earlier draft of this PRD, which gave `Fact` a `quote: str` field holding a verbatim copy of the cited text. The owner's decision: the LLM's grounding call still emits a `quote` field exactly as before (03 §4.1/§4.2 — unchanged prompt, unchanged verbatim-substring check), because a model that invents evidence cannot produce a real substring of the source, which is what makes fabrication mechanically detectable. What changes is what happens *after* that check passes — 03's `_locate_quote_offsets` (03 §4.3) deterministically finds the verified quote inside the cited unit's raw text and records only its location, never a second copy of the text. The source a job run operates on is deterministic and unchanging for that run (units are recomputed by the pure function `unitize(input_text, input_provenance)`, 02), so a pointer is sufficient; a copy would duplicate patient source text inside the ledger for no benefit. The offsets themselves are always code-computed, never model-produced — the model cannot be trusted to count characters, so it is never asked to. See `quote_for()` immediately below for how 04/05 recover the text these offsets point at.
- **`Fact.text`** — the fact's own content at clause granularity, distinct from the LLM's `quote`. The brief draws exactly this distinction ("a verbatim quote, and the fact's content at clause granularity" — brief §3.3) — the quote is evidence (verified, then discarded in favor of its location), `text` is the extracted clause 04 will render into a `CarePlan` field, and it is the one piece of the LLM's four-field output that is actually stored verbatim on `Fact`. It may overlap substantially with the evidence quote but is not required to be identical (e.g. the LLM's `quote` might be `"metoprolol 25mg BID"` while `text` is the fuller clause `"Continue metoprolol 25 mg twice daily"` per the brief's own worked example in §2.5).
- **`quote_for(fact, units_by_id)`** — lives in this module, alongside `Fact`, rather than in `services/unitizer.py` (02's file): it is a one-line lookup over `Fact`/`Unit` data with no unitization logic of its own, so colocating it with the two models it reads keeps 04/05 to a single import from the module that already defines the ledger contract, instead of adding a cross-PRD import onto 02 for a helper that doesn't unitize anything. 04 and 05 (owned by another workstream in this pass) must call this helper wherever they need the evidence text — `Fact.quote` does not exist, and reading a nonexistent attribute is a hard `AttributeError`, not a silent fallback.

Both models inherit `JsonModel` (`backend/models/base.py`) — `extra="forbid"`, `to_dict()`/`from_dict()` — identical strictness posture to every other backend model. No length constraints on `quote`/`text` beyond `str`, matching the rest of the codebase's convention of not imposing Pydantic-level string length caps.

### 4.4 `firestore.rules`

Old:
```
match /care_plan_outputs/{docId} {
  allow get: if resource == null
              || (request.auth != null && request.auth.uid == resource.data.uid)
              || resource.data.shared == true;
  allow list: if request.auth != null && request.auth.uid == resource.data.uid;
  allow write: if false;
}
```

New:
```
match /care_plan_outputs/{docId} {
  allow get: if resource == null
              || (request.auth != null && request.auth.uid == resource.data.uid);
  allow list: if request.auth != null && request.auth.uid == resource.data.uid;
  allow write: if false;
}
```

The `|| resource.data.shared == true` clause is deleted. The task brief asks me to additionally consider whether `JobDoc.shared` itself should go — **recommendation: yes, delete it.**

Verified via grep: `JobDoc.shared` (`backend/models/job.py:55`, set `False` in `for_single` at line 94) has exactly one production consumer — the rules clause just deleted — and zero frontend consumers. It is a field that can only ever hold `False`, forever, with no code path that flips it and no feature that would give it meaning (brief: "no share feature exists" — decision log row 1). Keeping a permanently-`False` field around is not "preserving information" (the "remove nothing" principle in the brief is scoped to *clinical content*, not dead infrastructure fields) — it's exactly the kind of vestigial surface the brief's `additional_info` reasoning ("the field has no prompt rule anywhere... vestigial from juno") argues against. Delete:

- `JobDoc.shared: Optional[bool] = None` (field declaration, `job.py:55`)
- `shared=False,` (the `for_single` factory kwarg, `job.py:94`)

### 4.5 `backend/app.py` CORS

Old (`app.py:38-50`):
```python
CORS(
    app,
    origins=[
        "https://juno-medical-clarity.web.app",
        "https://juno-medical-clarity.firebaseapp.com",
        "http://localhost:5173",
    ],
    methods=[...],
    allow_headers=[...],
    expose_headers=[...],
    supports_credentials=False,
    max_age=600,
)
```

New — add a small resolver above the `CORS(...)` call and pass its result as `origins`:

```python
_DEFAULT_CORS_ORIGINS = [
    "https://juno-medical-clarity.web.app",        # production Firebase Hosting site
    "https://juno-medical-clarity.firebaseapp.com",  # Firebase Hosting's alternate default domain
    "http://localhost:5173",                       # frontend dev server
]


def _cors_allowed_origins() -> list[str]:
    """CORS_ALLOWED_ORIGINS is a comma-separated list, e.g.
    "https://abcd1234.ngrok-free.app,http://localhost:5173". Falls back to
    the hardcoded production + local-dev origins when unset or empty, so
    production behavior is unchanged with no env var configured."""
    raw = _os.environ.get("CORS_ALLOWED_ORIGINS", "")
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    return origins or _DEFAULT_CORS_ORIGINS


CORS(
    app,
    origins=_cors_allowed_origins(),
    methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Session-Id"],
    expose_headers=["X-Session-Id", "X-Trace-Id"],
    supports_credentials=False,
    max_age=600,
)
```

`methods`/`allow_headers`/`expose_headers`/`supports_credentials`/`max_age` are unchanged — only `origins` becomes configurable. Also add the env var name to `Constants.EnvVars` for documentation consistency with the class's existing purpose (it already documents `SERVICE_MODE`, `K_SERVICE`, etc., even though `app.py` doesn't consistently reference `Constants.EnvVars.*` for env var names it reads — e.g. `SERVICE_MODE = _os.environ.get("SERVICE_MODE", "api")` at `app.py:57` reads the raw literal, not `Constants.EnvVars.SERVICE_MODE`). Given that existing inconsistency, using the raw string literal `"CORS_ALLOWED_ORIGINS"` directly in `app.py` (as shown above) matches the file's actual current style; adding `CORS_ALLOWED_ORIGINS: str = "CORS_ALLOWED_ORIGINS"` to `Constants.EnvVars` is a one-line documentation addition, not a behavior change — do both.

### 4.6 `backend/utils/misc.py` — `derive_output_name` fallback (discovered dependency)

Not named in the task brief's file list, but a direct, mechanical consequence of deleting `Diagnosis.main_conclusion` (§4.1): `derive_output_name` (`backend/utils/misc.py:14-52`, the only consumer of `diagnosis.main_conclusion` outside the schema itself — verified by repo-wide grep) uses it as its second-priority fallback for naming a completed job:

```python
diagnosis = care_plan_data.get("diagnosis") or {}
main = (diagnosis.get("main_conclusion") or "").strip()   # always "" once main_conclusion is gone
if main:
    first_sentence = main.split(".")[0].strip()
    if first_sentence:
        return first_sentence[:60]
```

Once `main_conclusion` no longer exists anywhere in the pipeline's output, this branch becomes permanently dead (the dict lookup always returns `""`), silently demoting every job that would have hit it straight to the filename fallback. **Fix: replace the priority-2 fallback source with `diagnosis.details[0].plain_name` (falling back to `.title` if `plain_name` is empty)** — the nearest surviving equivalent of "a short, human diagnosis label," which `main_conclusion` provided and `details[]` still does:

```python
diagnosis = care_plan_data.get("diagnosis") or {}
details = diagnosis.get("details") or []
if details:
    label = (details[0].get("plain_name") or details[0].get("title") or "").strip()
    if label:
        return label[:60]
```

This is a small, in-scope fix (same function, same file, direct consequence of a schema field this PRD deletes) — not a new sub-project. `derive_output_name` is called from `routes/worker.py:192`, which is unaffected (same call signature, same return type).

## 5. API Change Summary

`CarePlanInternal.care_plan` (the `care_plan` key inside `output_data`, the only place `CarePlan` reaches an HTTP response) changes shape:

| Key | Before | After |
|---|---|---|
| `urgency` | present, `"normal"\|"caution"\|"concern"\|"urgent"` | **removed** |
| `additional_info` | present, `list[str]` | **removed** |
| `diagnosis.main_conclusion` | present, `str` | **removed** |
| `*.importance` (medications/tests/procedures/other/warning_signs) | present, `"high"\|"low"` | **removed** |
| `*.source` (same 5 models) | present, `"documents"\|"recording"\|"notes"\|null` | **removed** |
| `warning_signs[].urgency` | always present, non-null, defaults `"monitor"` | present, **may be `null`** |
| `medications[].status`, `tests[].status`, `procedures[].status`, `other[].status`, `follow_up[].status` | absent | **added**, always `"to_do"\|"done"`, never absent/null |
| `medications[].change` / `.change_description` | two fields (`bool`, `str`) | **one field** `change: str` |
| `summary_fact_ids` | absent | **added to the internal `CarePlan` model**, but stripped at `routes/worker.py` before `output_data` is persisted (§4.1's internal-provenance-fields note) — **never present** in the API response |
| `medications[].source_fact_ids`, `tests[].source_fact_ids`, `procedures[].source_fact_ids`, `other[].source_fact_ids`, `follow_up[].source_fact_ids`, `warning_signs[].source_fact_ids` | absent | **added to the internal model** (all six item models), same stripping treatment as `summary_fact_ids` — **never present** in the API response |
| `raw` | present when populated (but already stripped before persistence — `routes/worker.py:198`) | **removed entirely** (field no longer exists on the model) |

No route signatures, HTTP status codes, or error shapes change. `CarePlanInternal`, `Metrics`, `Grading`, `Input` are untouched. The `Unit`/`Fact` ledger models introduced in `backend/models/ledger.py` never appear in any API response — they are pipeline-internal only (§4.1.4, §4.3). Nor do `summary_fact_ids` or any `*.source_fact_ids`: both are declared on `CarePlan` and its item models (so they round-trip through internal pipeline state exactly like any other field, `extra="forbid"` included) but are stripped at the `routes/worker.py` boundary before `output_data` is persisted or returned — see §4.1's internal-provenance-fields note for the fix this PRD specifies (and flags for 06 to land, since it lives in `routes/worker.py`).

## 6. Frontend Change Summary

**N/A for this PRD's own file scope** — `frontend/src/types/carePlan.ts` and every `.tsx` consumer belong to sub-project 08. This PRD makes no frontend changes.

**Contract 08 must match** — the backend `CarePlanContent` shape 08's TypeScript types need to converge on, derived directly from §4.1/§5:

```typescript
interface CarePlanContent {
  summary: string;
  // summary_fact_ids: declared on the backend CarePlan model, but stripped
  // at the routes/worker.py boundary before the API response — 08 never
  // receives it, so it is intentionally absent from this interface, not
  // an oversight (ledger/citations are internal — brief §3.10).
  reason_for_visit: Array<{ reason: string; description: string }>;
  diagnosis: {
    // main_conclusion REMOVED — do not reference it
    changed_since_last_visit?: string;
    details: DiagnosisDetail[];
  };
  medications: Array<{
    title: string; plain_name?: string; why?: string;
    dosage?: string; frequency?: string; timing?: string; duration?: string;
    instructions?: string; side_effects_to_watch?: string;
    status: 'to_do' | 'done';               // NEW, always present
    change: string;                         // CHANGED — was `change?: boolean` + `change_description?: string`; now one string, "" means nothing to report
    // importance, source REMOVED
  }>;
  tests: Array<{ ...; status: 'to_do' | 'done' }>;       // status NEW; importance, source REMOVED
  procedures: Array<{ ...; status: 'to_do' | 'done' }>;  // status NEW; importance, source REMOVED
  other: Array<{ ...; status: 'to_do' | 'done' }>;       // status NEW; importance, source REMOVED
  follow_up: Array<{ time_frame: string; description: string; status: 'to_do' | 'done' }>; // status NEW
  warning_signs: Array<{
    symptom: string; what_it_might_mean?: string; what_to_do: string;
    urgency: 'emergency' | 'call_doctor' | 'monitor' | 'normal_side_effect' | null;  // CHANGED — was always non-null, defaulted "monitor"; now always present as a key but value may be null
    related_to?: string;
    // importance, source REMOVED
  }>;
  questions: string[];
  low_priority: string[];
  terms?: TermsMap;
  // additional_info REMOVED — delete the field and the "Data Sources" card entirely (CarePlanView.tsx:348)
  // raw REMOVED — was never rendered anyway (frontend never read `.raw`)
  // urgency (top-level) REMOVED — verified zero frontend consumers (grep found none outside warning_signs' own urgency)
}
```

None of the six item types' new `source_fact_ids` field appears in this interface either, for the same reason `summary_fact_ids` doesn't: both are stripped server-side before the API response (§4.1, §5). 08's TypeScript types need no `source_fact_ids`/`summary_fact_ids` field on any interface — omitting them entirely is the correct match to the actual wire contract, not an oversight.

08 also needs, from `CarePlanView.tsx`'s existing null-handling patterns: `URGENCY_ORDER`/`URGENCY_COLORS`/`URGENCY_LABELS` lookups (`CarePlanView.tsx:267-274`) currently index by `sign.urgency` assuming it's always a valid key; once `urgency` can be `null`, those lookups need a null-safe path (the brief specifies: null renders grey, sorts last — brief decision-log row "Null urgency renders grey, sorts LAST, and is never removed"). This is 08's implementation, not this PRD's, but the schema-level trigger for that work is exactly `warning_signs[].urgency` going nullable here.

## 7. Testing

### 7.1 Files with breaking changes identified

| File | What breaks | What it should assert instead |
|---|---|---|
| `backend/tests/fixtures/care_plan.json` | Contains `urgency`, `additional_info`, `diagnosis.main_conclusion`, `importance` and `source` on every item, no `status`, `medications[0].change`/`change_description` as two fields, `raw` object, `warning_signs[0].urgency` as non-null | Rewrite the fixture to the new shape: drop the five removed-field families and `raw`/`additional_info`; add `status` to every medication/test/procedure/other/follow_up entry; fold `change`+`change_description` into one `change` string; add `summary_fact_ids: [1, 2, 3]` (small, non-empty, to exercise the round-trip) and a small non-empty `source_fact_ids` (e.g. `[1]`) on one entry in each of the six item lists, exercising the round-trip for those too |
| `backend/tests/models/test_care_plan.py::test_care_plan_round_trips_full_fixture` | Fixture drift (above) | No code change needed once the fixture is fixed — this test just round-trips whatever the fixture contains |
| `backend/tests/models/test_care_plan.py::test_care_plan_rejects_extra_top_level_key` / `::test_care_plan_rejects_extra_nested_key` | None directly — mechanical, keys off the (fixed) fixture | No change needed |
| `backend/tests/models/test_care_plan.py::test_care_plan_minimal_payload_uses_pipeline_defaults` | `assert model.urgency == "normal"` — field no longer exists, `AttributeError` | Delete that one assertion line; everything else in the test (empty-list defaults for `reason_for_visit`, `medications`, etc.) is unaffected since an empty list never triggers the new `status`-required validation |
| `backend/tests/models/test_care_plan.py::test_structured_llm_schema_properties_match_care_plan_structured_fields` | None — mechanical set-difference test against `care_plan.pipeline._llm_schema`; `.pop(field, None)` on an already-absent `"raw"` key is a no-op, so this passes unchanged regardless of landing order relative to 06 | No change needed in this PRD. Flag for 06: once `raw` no longer exists on `CarePlan` at all, `_STRUCTURING_SCHEMA`'s `exclude={"terms", "raw"}` (`care_plan/pipeline.py:61`) no longer needs `"raw"` in the exclude set — harmless to leave, but 06 should clean it up when it rewires this file |
| `backend/tests/models/test_readpath_tolerance.py::test_care_plan_without_raw_validates_for_free_read_tolerance` | Pops `"raw"` from the fixture then validates — once `CarePlan` has no `raw` field at all, there is nothing left to demonstrate "tolerates this optional field's absence" for; the test's *premise* (raw is optional and might be legitimately missing from an older doc) no longer applies since the field doesn't exist | **Repoint, don't delete.** Rename to `test_care_plan_without_note_validates_for_free_read_tolerance` and pop `"note"` instead (`CarePlan.note: str \| None = None` is already optional and untouched by this PRD) — this preserves the regression-guard pattern ("no migration code; this is only free read tolerance" per the test's own docstring) for the next optional field someone adds, rather than losing that coverage entirely |
| `backend/tests/models/test_job.py::test_for_single_sets_shared_trace` | `assert job.shared is False` — `JobDoc.shared` deleted (§4.4) | Delete that assertion line; keep the rest (`trace_id`, `status` assertions). Consider renaming the test to `test_for_single_sets_trace` since "shared" is no longer part of what it verifies |
| `backend/tests/routes/test_jobs_e2e_scenarios.py::test_firestore_rules_static_review_note` | Docstring quotes the old 3-clause rule including `\|\| resource.data.shared == true`, and its prose explanation ("uid check and the shared check") no longer describes the actual file | Update the docstring to quote the new 2-clause `allow get` rule and drop the "shared check" sentence — the remaining explanation (uid check denies user B, write is unconditionally denied) still holds verbatim |
| `backend/tests/routes/test_jobs_e2e_scenarios.py::_build_care_plan` (helper, not a test itself, used by every size/serialization test in this file) | Constructs `Medication`/`Test`/`Procedure`/`WarningSign` with `importance="high"/"low"`, `GlossaryTerm(source="notes")` is fine (glossary `source` is a different, untouched field — see §4.2's grep confirming `Constants.Enums.SOURCE` has no other consumers), `Diagnosis(main_conclusion=...)`, and `RawArtifacts(...)` — every one of these kwargs will raise `TypeError`/`ValidationError` under `extra="forbid"` the moment §4.1 lands, so **every test in this file that calls `_build_care_plan` fails to even construct its fixture** | Remove `importance=` from all four call sites (Medication ×1, Test ×1, Procedure ×1, WarningSign ×1); add required `status="to_do"` (or `"done"` for variety) to Medication/Test/Procedure/FollowUp instantiations; remove `main_conclusion=` from the `Diagnosis(...)` call; remove the `raw = RawArtifacts(...)` line and the `raw=raw` kwarg on the final `CarePlan(...)` call entirely |
| `backend/tests/routes/test_jobs_e2e_scenarios.py` — doc-size-budget assertions (the ones this file's `_doc_size_bytes`/`_max_leaf_string_bytes` helpers exist to support) | These tests use `RawArtifacts(text="x"*3000, simplified_text="y"*3000, clarified_text="z"*3000)` — 9000 characters — as a major contributor to pushing a test `CarePlan` toward realistic/near-limit Firestore document sizes. Once `raw` doesn't exist, that padding mechanism is gone, and whatever specific byte-count thresholds those tests assert may no longer be reachable or meaningful the same way | **Division of labor, resolved here**: this PRD's responsibility is only to make the test suite *compile and construct valid models* again (the fixes above accomplish that — the file will run without `TypeError`/`ValidationError`). Recalibrating the actual size-budget *thresholds* now that a major padding source is gone is out of this PRD's scope: it requires understanding `routes/worker.py`'s persistence logic (including the now-dead `.pop("raw", None)` call noted in §4.1.4), which 06 owns. Recorded as `[RESOLVED: division of labor]` in §9, not left ambiguous |
| `backend/tests/utils/test_misc.py::test_diagnosis_fallback` | `derive_output_name({"reason_for_visit": [], "diagnosis": {"main_conclusion": "Hypertension. More details."}})` expects `"Hypertension"` — `main_conclusion` key is simply ignored by the fixed function (§4.6), falls through to the next fallback | Rewrite the fixture input to the new shape and expectation: `derive_output_name({"reason_for_visit": [], "diagnosis": {"details": [{"plain_name": "Hypertension"}]}})` should return `"Hypertension"` |
| `frontend/src/tests/fixtures/realCarePlanOutput.fixture.json` | Same drift as the backend fixture (`urgency`, `additional_info`, `main_conclusion`, `importance`/`source` per item, `raw` object present, no `status` fields) — owned by 08, not edited by this PRD, but flagged here per the task's explicit instruction to check it | 08 must regenerate this fixture against the new backend contract (§6) before any frontend test relying on it will pass. Not actioned in this PRD; recorded as a dependency for 08 |

### 7.2 Files checked and confirmed unaffected

- `backend/tests/models/test_envelope.py` — its `_care_plan()` helper builds a minimal `CarePlan(summary=..., terms=...)` with no medications/tests/etc. and never references any deleted field. Confirmed by direct read: no change needed.
- `backend/tests/models/test_base.py` — tests `JsonModel` generically via a local `SimpleModel`, no `CarePlan` reference at all.
- `backend/tests/care_plan/test_pipeline_schema.py`, `test_pipeline_structure.py`, `test_pipeline_executors.py`, `test_pipeline_streaming.py`, `test_pipeline_prompts.py` — grepped for every deleted field name (`importance`, `urgency`, `main_conclusion`, `additional_info`, `RawArtifacts`, `source=`); zero hits outside prose describing prompt *rules* (e.g. "Do not add urgency unless the source implies urgency" — English text inside a prompt-content assertion, not a schema field reference). These files test `care_plan/pipeline.py`, which 06 rewires; they are not broken by this PRD but will need substantive rewrites once 06 lands — out of this PRD's scope.
- Repo-wide grep for `Medication(`, `Test(`, `Procedure(`, `OtherInstruction(`, `WarningSign(`, `FollowUp(` constructor calls across `backend/tests/` found exactly one file (`test_jobs_e2e_scenarios.py`, handled above) besides `test_care_plan.py` (which only builds via fixture dict, not constructor kwargs) — confirmed no other hidden construction sites.

### 7.3 New tests this PRD should add

- `backend/tests/models/` gets a new `test_ledger.py` (or a `test_ledger.py` under wherever 02/03 land theirs — recommend creating a minimal one here since the models exist here): round-trip a `Unit` and a `Fact` through `to_dict()`/`from_dict()`; assert `extra="forbid"` rejects an unknown key on each — specifically assert that a `quote` key is rejected on `Fact` (`extra="forbid"` should raise `ValidationError`, not silently ignore it — a regression guard against the old field's name being reintroduced by habit); assert `Fact.category` rejects a value outside the eight-item `Literal`; assert `Fact` requires `char_start`/`char_end`/`id`/`category`/`unit_id`/`text` (no defaults) and has no `quote` attribute after construction. This gives 02/03 a model-correctness baseline they don't have to write themselves before their own logic tests land.
- Same file: `test_quote_for_returns_unit_text_slice` — construct a `Unit` with known `text`, a `Fact` citing it with `char_start`/`char_end` matching a known substring, call `quote_for(fact, {unit.id: unit})`, assert the returned string equals that substring exactly (byte-for-byte, since `quote_for` does a plain Python slice with no normalization). `test_quote_for_raises_key_error_on_unknown_unit_id` — `units_by_id` missing the fact's `unit_id`; assert `KeyError` (documents that `quote_for` does not itself validate `unit_id` — callers are expected to have built `units_by_id` from the same unit list `_verify_ledger` already validated against).
- `backend/tests/models/test_care_plan.py`: add one new test asserting `WarningSign(...)` without `urgency=` raises `ValidationError` (proves "no default" actually took, since a missing `= None` default is easy to typo back in during implementation) and one asserting `WarningSign(urgency=None, ...)` validates successfully (proves nullable actually took).
- `backend/tests/models/test_care_plan.py`: add one test asserting `Medication(...)` (or any of the five) without `status=` raises `ValidationError` — same "prove the required-ness actually took" guard.
- `backend/tests/models/test_care_plan.py`: add one test per one of the six item models (e.g. `Medication`) asserting construction with no `source_fact_ids=` succeeds and defaults to `[]`, mirroring the existing implicit coverage `summary_fact_ids`'s default already gets from `test_care_plan_minimal_payload_uses_pipeline_defaults`.
- `backend/tests/routes/test_worker.py`: add `test_job_completed_output_has_no_summary_fact_ids` and `test_job_completed_output_has_no_source_fact_ids`, mirroring the existing `test_job_completed_output_has_no_raw` (`test_worker.py:425-463`) pattern exactly — mock `envelope.to_dict()` to return a `care_plan` dict with a populated `summary_fact_ids: [1, 2]` and at least one item carrying `source_fact_ids` (e.g. `medications: [{"title": "...", "source_fact_ids": [3]}]`), then assert `"summary_fact_ids" not in saved_output_data["care_plan"]` and `"source_fact_ids" not in saved_output_data["care_plan"]["medications"][0]`. This is the test that proves the fix specified in §4.1's internal-provenance-fields note; it lands whenever that fix does (flagged there for 06, since it's in `routes/worker.py`), but the test spec belongs to this PRD since it's this PRD's schema decision the fix protects.

## 8. Manual Intervention Required From You

- **Firebase Auth authorized domains**: when you start an ngrok tunnel for local `SERVICE_MODE=combined` testing, you must add that session's ngrok domain to Firebase Auth's authorized domains list yourself (Firebase Console → Authentication → Settings → Authorized domains). Not automatable from here — it's a console action tied to your Firebase project.
- **`CORS_ALLOWED_ORIGINS` per session**: with the change in §4.5, you set `CORS_ALLOWED_ORIGINS=https://<your-ngrok-domain>.ngrok-free.app,http://localhost:5173` (or similar) in your local environment before starting the backend each time you tunnel, since free ngrok domains rotate on restart. No code change needed per session anymore — this is exactly what §4.5 was built to enable, but the env var still has to be set by you locally (this PRD only makes it possible, not automatic — there is no way for the backend to know your ngrok domain in advance).

## 9. Open Questions & Decisions

- `[RESOLVED: CarePlan.summary_fact_ids is a sibling list field (list[int]), not a wrapper object around summary]` — see §4.1 for the four-point rationale (frontend-render simplicity, precedent, review-check simplicity, no UI reason to co-locate).
- `[RESOLVED: Medication, Test, Procedure, OtherInstruction, FollowUp, and WarningSign (all six item models) each get a source_fact_ids: list[int] = Field(default_factory=list), the identical shape and default as summary_fact_ids.]` — see §4.1's "Fact-ID citation fields" section for the shared rationale (mirrors `summary_fact_ids` exactly: sibling list, not a wrapper; never rendered).
- `[RESOLVED: Fact drops quote: str and gains char_start: int / char_end: int — Python slice offsets into the cited Unit.text. The grounding LLM's prompt and its verbatim-substring check are UNCHANGED (03 §4.1/§4.2); only what happens after that check passes changes — 03 deterministically locates the verified quote and records its location instead of a second copy of the text. quote_for(fact, units_by_id) -> str, added to models/ledger.py alongside Fact, rehydrates the text on demand for 04's assembly prompt and 05's corrector.]` — the source text a job run operates on is deterministic and unchanging for that run (units are recomputed by the pure function `unitize(input_text, input_provenance)`, 02), so a pointer is sufficient and a copy would duplicate patient source text inside the ledger for no benefit. `quote_for` lives beside `Fact` (not in `services/unitizer.py`, 02's file) because it is a one-line lookup over `Fact`/`Unit` data with no unitization logic of its own — colocating it with the models it reads keeps 04/05 to one import from the module that already defines the ledger contract. 04 and 05 must switch every place that would have read `Fact.quote` to call `quote_for()` instead; noted as a dependency here since those PRDs are maintained separately from this pass.
- `[RESOLVED: summary_fact_ids and source_fact_ids must never reach the API response, the frontend, or the PDF — both are internal provenance, no different in kind from the ledger they cite into. No stripping mechanism for either exists today (both are new fields with zero references anywhere in backend/ as of this PRD); the fix is specified in §4.1's internal-provenance-fields note (two new pop-based lines alongside routes/worker.py's existing raw/input.text stripping at worker.py:202-203) and flagged for 06 to implement, since routes/worker.py is 06's file per this PRD's Non-Goals.]` — this reverses an earlier draft of this PRD's own reasoning for `summary_fact_ids`, which argued it didn't need stripping because it's small; that reasoning was about Firestore document size, not exposure risk, and answered the wrong question.
- `[RESOLVED: the project's evidence/coverage contract is soundness, not completeness. The checkable property, going forward: every care-plan item cites at least one fact via source_fact_ids, and every id in summary_fact_ids/source_fact_ids exists in the ledger. A ledger fact that no output item cites is legitimate, not an error — the assembly LLM (04) selects what belongs in a patient-facing report under its AHRQ-guided prompt, and not every extracted fact belongs there. Tradeoff, stated once here: omission is no longer mechanically detectable and becomes a prompt-quality concern for 04's assembly step; fabrication remains mechanically detectable (03's three deterministic checks against source text, and the citation-existence property this schema defines — every `summary_fact_ids`/`source_fact_ids` entry must name a real `Fact.id` — which 05 is responsible for checking).]` — this is a project-wide inversion from an earlier draft's assumption that closing the ledger meant checking every fact appears in the output; that assumption is corrected everywhere it appeared in this PRD (the `Fact.id` rationale above, and the coverage-check framing that used to justify it) and in 03 (which states the identical contract in its own §9 and additionally corrects its Non-Goals wording). 04 (assembly) is what populates `source_fact_ids`, and 05 (review) is what checks it — both are out of this pass's file scope, but the contract they must implement is settled here.
- `[RESOLVED: Medication.change/.change_description fold to a single change: str = "" field, empty string meaning "nothing to report"]` — matches the schema's existing string-default idiom used throughout `Medication` and every other model.
- `[RESOLVED: RawArtifacts and CarePlan.raw are deleted outright; nothing replaces them on the CarePlan model. The grounding ledger travels as pipeline-internal dataclass state (models/pipeline_events.py, owned by 06), never touching CarePlan or Firestore.]` — grounded in the verified fact that `raw` was already stripped before persistence (`routes/worker.py:198`) and the brief's explicit statement that the ledger must not be patient-visible (§3.10).
- `[RESOLVED: Unit and Fact live in a new flat module, backend/models/ledger.py, not a new subpackage and not inside models/care_plan/.]` — matches the repo's existing flat-module precedent (`grading.py`, `input.py`, `metrics.py`) and keeps the ledger visually and structurally separate from the `CarePlan` family it is deliberately not part of.
- `[RESOLVED: Fact gets its own id: int field, even though the task brief's §B bullet list for Fact doesn't name it explicitly.]` — required by `summary_fact_ids`/`source_fact_ids` (which need something to cite) and by the citation-existence check every cited id must pass (05: "does every id in `summary_fact_ids`/`source_fact_ids` name a real fact" — see the soundness-contract entry below for why this replaces an earlier, opposite-direction framing). Filling this gap rather than leaving it open because both downstream requirements are unambiguous in the approved brief; there was no plausible alternative reading.
- `[RESOLVED: FactCategory's eight Literal values are spelled identically to CarePlan's own top-level field names (reason_for_visit, diagnosis, medications, tests, procedures, other, follow_up, warning_signs), with "diagnosis" mapping to CarePlan.diagnosis.details specifically.]` — makes 04's category→field mapping a direct dict lookup.
- `[RESOLVED: JobDoc.shared is deleted, not just the firestore.rules clause that reads it.]` — zero remaining consumers after the rules clause is removed; permanently-`False` dead field, not clinical content the "remove nothing" principle protects.
- `[RESOLVED: Constants.Enums (the now-empty container class) is deleted along with its two member enums, SOURCE and IMPORTANCE.]` — zero remaining members, zero remaining consumers.
- `[RESOLVED: derive_output_name's (backend/utils/misc.py) priority-2 fallback moves from diagnosis.main_conclusion to diagnosis.details[0].plain_name (or .title), in-scope for this PRD since it's a direct, mechanical consequence of deleting main_conclusion, confined to one function in one file.]`
- `[RESOLVED: this PRD fixes only compile/construct-time breakage in backend/tests/routes/test_jobs_e2e_scenarios.py (removing deleted-field kwargs, adding required status kwargs). Recalibrating that file's document-size-budget thresholds now that RawArtifacts padding is gone is deferred to 06, which owns routes/worker.py and the persistence logic those thresholds test against.]`
- `[RESOLVED: backend/tests/models/test_readpath_tolerance.py's existing test is repointed to CarePlan.note (already optional, untouched) rather than deleted, preserving the "no migration code, free read-path tolerance" regression-guard pattern for future optional fields.]`
- `[RESOLVED: Constants.Schema.CARE_PLAN_VERSION stays "1.2" — no version bump.]` — the global constraint is explicit (mutate in place, no `v1-3`), and there is no live document population for a version bump to signal anything to.
- `[DEFERRED: persisting the grounding ledger anywhere (e.g. for the future clinical-fidelity eval harness to consume) is out of scope — that harness itself is explicitly deferred per the parent brief's Non-Goals, and building storage for a consumer that doesn't exist yet would be exactly the kind of speculative surface the brief argues against.]`
- `[DEFERRED: Constants.Pipeline.PIPELINE_STEPS enum changes (new step members/labels for GROUND/ASSEMBLE_RENDER/REVIEW/CORRECT) — explicitly 06's territory per the parent brief's decomposition table, even though it lives in the same constants.py file this PRD edits for the SOURCE/IMPORTANCE deletion.]`
- `[OPEN]` — none remaining. Every decision the task brief asked this PRD to make (§A–§E of the task) has a resolution above; nothing here blocks `dev-tasks` from generating tasks for sub-project 01 deterministically.
