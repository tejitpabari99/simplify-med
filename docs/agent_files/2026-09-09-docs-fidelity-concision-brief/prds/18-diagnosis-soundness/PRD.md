# PRD 18 — Diagnosis and Reason-for-Visit Soundness

Parent brief: `docs/agent_files/2026-09-09-docs-fidelity-concision-brief/brainstorm.v1.md` (approved; not re-litigated here).
Branch: `docs/fidelity-concision-brief`.
Depends on: 01 (`backend/models/care_plan/care_plan.py` — owns the `source_fact_ids` shape this PRD extends; `backend/models/ledger.py` — `FactCategory`, unchanged, read only), 04 (`backend/care_plan/pipeline.py` — owns `_verify_assembly`, `_ITEM_LIST_FIELDS`, `_log_thin_fields`, and `backend/care_plan/prompts/assemble_and_render.txt`, all extended here), 05 (review/correct — `_resolve_path`, `_diff_item`, `review.txt`, `correct.txt`; read to confirm no code change is required there), 06 (`backend/routes/worker.py` — owns `_strip_internal_provenance`, extended here), 13 (edits the same two files this PRD edits — `care_plan.py` and `assemble_and_render.txt` — for an unrelated field, `why`; seam stated in §4.8), 14 (rejected `merged: bool` as an unverifiable model self-report; its reasoning is the template this PRD follows for rejecting a similar self-report field for `low_priority`, §4.6).
Depended on by: none identified in 15/16/17 as of this writing (grepped for `reason_for_visit`/`DiagnosisDetail`/`diagnosis.details`, zero hits — those PRDs may not yet exist as files). Any future PRD that adds a new `CarePlan` field must satisfy the regression test this PRD adds (§7.5). Soft dependency, the other direction: PRD 14 (merge-provenance) relies on the free `len(source_fact_ids) > 1` signal to make merges findable in logs, but recorded that signal as structurally unavailable for diagnosis-category merges (its own §9 `[OPEN]`, since resolved) because `DiagnosisDetail` carried no `source_fact_ids`. This PRD's §4.2 addition closes that gap as a side effect — 14 does not block on 18 landing, but 14's diagnosis-merge observability arrives only once 18 does.

## 1. Problem

The project's headline evidence contract — stated in `prds/README.md`'s "Consolidated open questions" item 2 and "Locked decisions" — is soundness: *every emitted care-plan item must cite at least one fact via `source_fact_ids`, and every cited id must exist in the ledger.* PRD 04 §4.4 enforces this in `_verify_assembly`, which filters each item's `source_fact_ids` against the ledger and drops any item left fully unbacked. This is the one deterministic guard in the whole pipeline built to stop a fabricated finding from reaching the patient.

**That guard has an undocumented blind spot covering the most clinically loaded content in the output.**

Verified at HEAD (`backend/care_plan/pipeline.py:349`):

```python
_ITEM_LIST_FIELDS = ("medications", "tests", "procedures", "other", "follow_up", "warning_signs")
```

`_verify_assembly` (`pipeline.py:394-434`) iterates only these six fields. Verified against `backend/models/care_plan/care_plan.py`: `source_fact_ids` appears on exactly these six item models — `Medication` (line 43), `Test` (53), `Procedure` (63), `OtherInstruction` (74), `FollowUp` (81), `WarningSign` (90).

`ReasonForVisit` (line 13-15) and `DiagnosisDetail` (line 18-23) carry **no `source_fact_ids` field at all** — grepped the full file, zero hits outside the six models above. `Diagnosis` (line 26-28) holds `changed_since_last_visit: str = ""` plus `details: list[DiagnosisDetail]`, and neither carries any citation surface either.

Yet `reason_for_visit` and `diagnosis` are two of the grounder's eight `FactCategory` members (`backend/models/ledger.py:35-44`: `reason_for_visit, diagnosis, medications, tests, procedures, other, follow_up, warning_signs`) — facts *are* extracted and tagged for them. `assemble_and_render.txt`'s MAPPING section instructs the model to map `reason_for_visit` facts into `reason_for_visit[]` and `diagnosis` facts into `diagnosis.details[]` (verified in the live prompt file, quoted in full in §4.4). And the frontend renders both into primary, un-collapsed patient-facing cards — verified in `frontend/src/components/CarePlanView.tsx`:

```
151:      {result.reason_for_visit?.length > 0 && (
152:        <ResultCard color="blue" icon="📅" title="Why You Came In">
...
162:      {result.diagnosis && result.diagnosis.details?.length > 0 && (
163:        <ResultCard color="teal" icon="🔍" title="What the Doctor Found">
```

Net effect: a fabricated diagnosis finding cannot be caught by the citation-existence guard, because there is no citation field to check. The only thing standing between an invented entry in "What the Doctor Found" and the patient is the `review` LLM call — which PRD 05 §4.8 makes **non-fatal** (a review failure ships assembly's output as-is), which the branch's own cited research (arXiv:2310.08118) documents as prone to rubber-stamping, and whose catch rate has **never been measured** (PRD 05 §7.5's evaluation protocol is specified but has not been run). Note that `review.txt`'s JOB 1 fidelity sweep and `correct.txt`'s `remove` op are *not* restricted to the six checked fields — `_resolve_path`/`_diff_item` (`pipeline.py:307`, `568`) resolve any dotted path generically, including `diagnosis.details[N]` (confirmed: `_split_array_path`'s own docstring at `pipeline.py:552` names `diagnosis.details` as a path it already handles). So an LLM reviewer *can* flag and remove a bad diagnosis item today — but only if it notices, and nothing deterministic backs that up the way `source_fact_ids` backs up the six covered fields.

This gap was missed by PRD 01 (which added `source_fact_ids` to six models and explicitly listed `Diagnosis`/`DiagnosisDetail`/`ReasonForVisit` as "out of this decomposition's six-model list" — PRD 01 §4.1 — without flagging the coverage consequence), PRD 04 (which built `_verify_assembly` against that six-field list), the full-branch adversarial review, and an external research comparison. It surfaced only when PRD 14 went looking for merge signals and found diagnosis merges invisible to any fact-based signal.

## 2. Goals

- Close the coverage gap: give `ReasonForVisit` and `DiagnosisDetail` a `source_fact_ids` field, and give `Diagnosis.changed_since_last_visit` an equivalent citation surface, mirroring the exact sibling-list shape PRD 01 already established for `CarePlan.summary`/`summary_fact_ids`.
- Extend `_verify_assembly` to enforce the citation-existence check against all three new surfaces, solving the nested-container shape problem `diagnosis.details` presents without inventing a generalized abstraction for a single occurrence.
- Update `assemble_and_render.txt` so the model actually populates the new fields, with an exact before/after of the MAPPING and SOURCE_FACT_IDS paragraphs.
- Extend `_strip_internal_provenance` so the new fields never reach the API response, matching the existing treatment of every other citation field.
- Make an explicit, written decision on `low_priority`'s soundness status — cover it or exempt it, but record the reasoning either way.
- Add a regression test that walks every `CarePlan` field and asserts it has a recorded soundness classification, so a future field cannot silently repeat this gap.

## 3. Non-Goals

- No fifth LLM call. Everything here is schema, prompt-text, and deterministic post-check changes inside the four-call pipeline that already exists.
- No change to `review.txt`'s or `correct.txt`'s prompt text, and no change to `_resolve_path`, `_diff_item`, `_verify_correction_diff`, or any other review/correct machinery — §4.7 confirms by direct inspection that this machinery already resolves arbitrary nested paths (including `diagnosis.details[N]`) generically, with no field allowlist to extend.
- No change to `_log_thin_fields`/`_RICHNESS_CHECKS` (content-richness floor, PRD 04 §4.4) — that check is about field length/informativeness, not citation existence, and already includes `reason_for_visit.description` and `diagnosis.details[].description` in its coverage.
- No versioning, no backward compatibility, no migration code — the schema mutates in place (global constraint).
- No frontend changes **except one named, bounded copy/guard change**: `CarePlanView.tsx`'s "What the Doctor Found" card render condition widens, and both it and `buildPdfHtml.ts` gain a fallback sentence for an emptied `diagnosis.details` (§6, resolving §9's former `[OPEN]` item on this). `frontend/src/types/carePlan.ts` is still not edited by this PRD — §4.6/§6 verify and state why none of the new `source_fact_ids`-shaped fields need TS mirroring.
- The clinical-fidelity evaluation suite (PRD 05 §7.5's unrun protocol) stays out of scope — this PRD closes the deterministic gap; it does not measure or improve the LLM reviewer's catch rate, which remains a separate, already-tracked open item.
- No change to `PRD 13`'s `why`-nullability work. Both PRDs touch `care_plan.py` and `assemble_and_render.txt`; §4.8 states the seam so both land cleanly regardless of order.

## 4. Architecture Decisions

### 4.1 Full `CarePlan` field audit

Every field on `CarePlan` and its two container models, audited against `_verify_assembly`'s coverage as it exists at HEAD, before this PRD's changes:

| Field | Model | Carries a citation field? | Checked by `_verify_assembly`? | Verdict |
|---|---|---|---|---|
| `summary` | `CarePlan` | via sibling `summary_fact_ids` | yes (`pipeline.py:409-415`) | covered |
| `reason_for_visit` | `CarePlan` → `ReasonForVisit` | **no** | no | **needs coverage — this PRD** |
| `diagnosis.details` | `CarePlan.diagnosis` → `DiagnosisDetail` | **no** | no | **needs coverage — this PRD** |
| `diagnosis.changed_since_last_visit` | `CarePlan.diagnosis` → `Diagnosis` (bare `str`) | **no** | no | **needs coverage — this PRD** |
| `medications` | `CarePlan` → `Medication` | `source_fact_ids` | yes | covered |
| `tests` | `CarePlan` → `Test` | `source_fact_ids` | yes | covered |
| `procedures` | `CarePlan` → `Procedure` | `source_fact_ids` | yes | covered |
| `other` | `CarePlan` → `OtherInstruction` | `source_fact_ids` | yes | covered |
| `follow_up` | `CarePlan` → `FollowUp` | `source_fact_ids` | yes | covered |
| `warning_signs` | `CarePlan` → `WarningSign` | `source_fact_ids` | yes | covered |
| `questions` | `CarePlan` (bare `list[str]`) | no | no | **deliberately exempt** — ungrounded by design (brief §2.5; `assemble_and_render.txt`'s QUESTIONS rule: a question may only ask about a genuine gap, never assert a fact) |
| `low_priority` | `CarePlan` (bare `list[str]`) | no | no | **exempt — reasoned in §4.6** (not previously documented anywhere; this PRD is the first place the exemption is written down) |
| `note` | `CarePlan` (`str \| None`) | n/a | n/a | **not applicable** — populated from upload metadata, never model output |
| `terms` | `CarePlan` → `GlossaryTerm` | n/a | n/a | **not applicable** — populated post-hoc by glossary curation (07) from a fixed reference wordlist (AHRQ/Michigan), never by the assembly LLM's clinical claims; `GlossaryTerm.source` is an unrelated pre-existing field naming which wordlist a definition came from, not a citation |
| `doc_type`, `version` | `CarePlan` (`Literal`) | n/a | n/a | **not applicable** — static tags, not content |
| `summary_fact_ids` | `CarePlan` | — (it *is* the citation field) | n/a | n/a |

Confirms the problem statement's claim exactly: six of nine content-bearing surfaces are covered; `reason_for_visit`, `diagnosis.details`, and `diagnosis.changed_since_last_visit` are not; `questions` is exempt by original design; `low_priority` was never decided either way until now.

### 4.2 `backend/models/care_plan/care_plan.py` — schema additions

Old → new, three models:

| Model | Field | Old | New |
|---|---|---|---|
| `ReasonForVisit` | `source_fact_ids` | — (absent) | **added**: `list[int] = Field(default_factory=list)` |
| `DiagnosisDetail` | `source_fact_ids` | — (absent) | **added**: `list[int] = Field(default_factory=list)` |
| `Diagnosis` | `changed_since_last_visit_fact_ids` | — (absent) | **added**: `list[int] = Field(default_factory=list)` |

```python
class ReasonForVisit(JsonModel):
    reason: str = ""
    description: str = ""
    source_fact_ids: list[int] = Field(default_factory=list)


class DiagnosisDetail(JsonModel):
    title: str = ""
    plain_name: str = ""
    description: str = ""
    what_it_means_for_you: str = ""
    severity: Literal["high", "medium", "low"] | None = None
    source_fact_ids: list[int] = Field(default_factory=list)


class Diagnosis(JsonModel):
    changed_since_last_visit: str = ""
    changed_since_last_visit_fact_ids: list[int] = Field(default_factory=list)
    details: list[DiagnosisDetail] = Field(default_factory=list)
```

Shape rationale — both new fields mirror precedent already settled elsewhere, not a new idiom:

- `ReasonForVisit.source_fact_ids` and `DiagnosisDetail.source_fact_ids` are the identical `list[int] = Field(default_factory=list)` shape PRD 01 gave the six existing item models. `ReasonForVisit` and `diagnosis.details[]` are exactly the same kind of "one care-plan item built from one-or-more facts" as `Medication`/`Test`/etc — PRD 01 §4.1 excluded them not on principled grounds but because the task brief it was implementing scoped "six models" explicitly; this PRD corrects that scope, not that reasoning.
- `Diagnosis.changed_since_last_visit_fact_ids` mirrors `CarePlan.summary`/`summary_fact_ids` — a bare string on a container gets a sibling `list[int]`, not a wrapper object, for the same four reasons PRD 01 §4.1 gave for `summary_fact_ids` (frontend never has to change how it renders the string; consistent with the existing flat-sibling pattern already used elsewhere on `CarePlan`; a flat list is the simplest input to a citation check; the field is never rendered to the patient so there's no UI reason to co-locate it with the text).
- **`changed_since_last_visit` is a latent instance of the same bug class, not a cosmetic afterthought.** It is a directly consequential, trend-asserting clinical claim ("your blood pressure has gotten worse since your last visit") on a container model that itself carries no citation surface — structurally identical to the diagnosis-detail gap this PRD's headline problem describes, just easier to miss because it's a single string rather than a list of objects. Covering it costs one field and no shape change (still a bare string; `= ""` still means "nothing to report" — PRD 01's fold-precedent for `Medication.change` is unaffected).
- All three new fields default to `[]` — a `default_factory=list`, not a required field. This is the single decision that keeps the test-fixture blast radius small; see §4.9.

### 4.3 `backend/care_plan/pipeline.py` — `_verify_assembly`'s coverage, and the nested-container mechanism

**The shape problem, stated precisely.** `_ITEM_LIST_FIELDS`' existing loop assumes `getattr(model, field)` returns a flat `list[SomeItemModel]` directly off `CarePlan` — true for all seven fields that will end up in that tuple (six existing plus `reason_for_visit`, which is structurally identical: a top-level `list[ReasonForVisit]`, each entry now carrying its own `source_fact_ids`). It is **not** true for `diagnosis`: `model.diagnosis` is a single `Diagnosis` instance (not a list), and the citable content lives one level down, at `model.diagnosis.details` (a list) and as a same-level sibling pair (`changed_since_last_visit` / `changed_since_last_visit_fact_ids`). `getattr(model, "diagnosis")` returns a `Diagnosis` object with no `.source_fact_ids` attribute at all — looping it through the existing flat mechanism would `AttributeError` immediately.

**Mechanism chosen: a second, dedicated block — not a generalized nested-path descriptor.** `diagnosis` is the only nested container on the entire `CarePlan` schema (verified by the field audit in §4.1). This project's own code already sets the precedent for handling exactly this shape: `_log_thin_fields` (`pipeline.py:367-391`) is a flat loop over `_RICHNESS_CHECKS` followed by one dedicated loop over `model.diagnosis.details` immediately below it, for the identical reason — one nested case doesn't justify inventing a generic "nested path" abstraction that no other caller needs. Building a reusable descriptor for a single occurrence would be exactly the kind of speculative complexity the project's "no versioning, mutate in place" posture argues against elsewhere; if a second nested container is ever added to `CarePlan`, that is the point at which factoring out a shared helper becomes justified by two real call sites, not one.

Old:

```python
_ITEM_LIST_FIELDS = ("medications", "tests", "procedures", "other", "follow_up", "warning_signs")
```

New:

```python
_ITEM_LIST_FIELDS = (
    "reason_for_visit", "medications", "tests", "procedures", "other", "follow_up", "warning_signs",
)
```

`reason_for_visit` needs no special-casing — it slots directly into the existing flat loop, since `ReasonForVisit` now carries `source_fact_ids` in the identical shape as the six original models.

`_verify_assembly` gains one new block, inserted after the existing `for field in _ITEM_LIST_FIELDS:` loop and before the final `return`:

```python
    # diagnosis is the one nested container on CarePlan -- model.diagnosis.details
    # is a list of DiagnosisDetail one level below CarePlan itself, so it cannot
    # sit in the flat _ITEM_LIST_FIELDS loop above. Handled as a second, dedicated
    # block, mirroring _log_thin_fields' own precedent (a flat loop, then one
    # dedicated loop for model.diagnosis.details) for the same reason: exactly
    # one nested container exists on the whole schema (PRD 18 §4.1's field
    # audit), and a generalized nested-path descriptor for a single occurrence
    # is speculative complexity this project's posture argues against.
    diagnosis_updates: dict = {}

    kept_details: list = []
    details_changed = False
    for detail in model.diagnosis.details:
        cited = [i for i in detail.source_fact_ids if i in valid_ids]
        if not cited:
            logger.warning(
                "assemble_and_render: dropping unbacked diagnosis.details item -- "
                "source_fact_ids=%r cited nothing in the ledger", detail.source_fact_ids,
            )
            details_changed = True
            continue
        if len(cited) != len(detail.source_fact_ids):
            logger.warning(
                "assemble_and_render: dropping hallucinated source_fact_ids on a "
                "diagnosis.details item: %s",
                [i for i in detail.source_fact_ids if i not in valid_ids],
            )
            detail = detail.model_copy(update={"source_fact_ids": cited})
            details_changed = True
        kept_details.append(detail)
    if details_changed:
        diagnosis_updates["details"] = kept_details

    if model.diagnosis.changed_since_last_visit:
        cited = [i for i in model.diagnosis.changed_since_last_visit_fact_ids if i in valid_ids]
        if not cited:
            logger.warning(
                "assemble_and_render: dropping uncited diagnosis.changed_since_last_visit "
                "claim (%r) -- source_fact_ids=%r cited nothing in the ledger",
                model.diagnosis.changed_since_last_visit,
                model.diagnosis.changed_since_last_visit_fact_ids,
            )
            diagnosis_updates["changed_since_last_visit"] = ""
            diagnosis_updates["changed_since_last_visit_fact_ids"] = []
        elif len(cited) != len(model.diagnosis.changed_since_last_visit_fact_ids):
            diagnosis_updates["changed_since_last_visit_fact_ids"] = cited

    if diagnosis_updates:
        updates["diagnosis"] = model.diagnosis.model_copy(update=diagnosis_updates)
```

**What "drop" means for a nested item.** For `diagnosis.details[N]`, drop means the identical operation as for any `_ITEM_LIST_FIELDS` entry — remove the `DiagnosisDetail` from the list — but the updated list has to be written back one level up, via `model.diagnosis.model_copy(update={"details": kept_details})`, then assigned into the top-level `updates["diagnosis"]`, rather than directly into `updates["<field>"]` the way a flat item's drop works. For `changed_since_last_visit`, "drop" means clearing the string to `""` and its fact-id list to `[]` — there is no array position to remove, so this reuses the exact convention `correct.txt` already defines for `summary`: *"If the path is exactly 'summary', set summary to '' instead (summary has no array position to delete)."* Applying the same convention to `changed_since_last_visit` keeps the codebase's "how do you delete a bare string claim" answer singular rather than inventing a second one.

**Should a fully-emptied `diagnosis.details` get different treatment, given an empty diagnosis card is itself a signal to the patient?** Yes — decided and specified, not deferred. `CarePlanView.tsx:162` today guards the whole "What the Doctor Found" card on `result.diagnosis.details?.length > 0`, identical to how every other item list disappears silently when empty. For a diagnosis specifically, that is the wrong signal: a fully-emptied `diagnosis.details` means the patient evidently had a visit but this PRD's new deterministic guard couldn't confirm any of it, and silent disappearance reads to the patient as "nothing was found" rather than "we couldn't verify what was found." This PRD overrides its own frontend Non-Goal (§3) for exactly this one case: the card's render condition widens to also fire on other evidence of a visit (`reason_for_visit` present, or `diagnosis.changed_since_last_visit` non-empty) even when `details` is empty, and in that empty-`details` case the card renders one fallback sentence instead of the details list. No new backend field or API signal is involved — this is a pure frontend render-condition and copy change, specified concretely in §6.

### 4.4 `backend/care_plan/prompts/assemble_and_render.txt` — prompt delta

Current MAPPING paragraph (verified against the live file):

```
MAPPING -- a fact's category decides which care-plan array it becomes an item in:
- reason_for_visit -> reason_for_visit[] (reason: a few words; description: one plain-language sentence)
- diagnosis -> diagnosis.details[] (title, plain_name, description, what_it_means_for_you; set severity ONLY if the fact itself states a severity judgement -- otherwise leave it null, never guess). If any diagnosis fact states something changed since the last visit, put that in diagnosis.changed_since_last_visit; otherwise leave it "".
```

New:

```
MAPPING -- a fact's category decides which care-plan array it becomes an item in:
- reason_for_visit -> reason_for_visit[] (reason: a few words; description: one plain-language sentence; source_fact_ids)
- diagnosis -> diagnosis.details[] (title, plain_name, description, what_it_means_for_you; set severity ONLY if the fact itself states a severity judgement -- otherwise leave it null, never guess; source_fact_ids). If any diagnosis fact states something changed since the last visit, put that in diagnosis.changed_since_last_visit and list the id(s) of the fact(s) that state it in diagnosis.changed_since_last_visit_fact_ids; otherwise leave both "" and [].
```

Current SOURCE_FACT_IDS paragraph:

```
SOURCE_FACT_IDS -- every medications, tests, procedures, other, follow_up, and warning_signs item must carry `source_fact_ids`: the id(s) of every fact you built it from (more than one id if MERGE below combines facts into one item). reason_for_visit and diagnosis items have no such field. Never leave source_fact_ids empty for an item you decide to include -- an item with no cited fact has nothing behind it and will not reach the patient.
```

New:

```
SOURCE_FACT_IDS -- every reason_for_visit, medications, tests, procedures, other, follow_up, and warning_signs item must carry `source_fact_ids`, and every diagnosis.details item must too: the id(s) of every fact you built it from (more than one id if MERGE below combines facts into one item). If diagnosis.changed_since_last_visit is non-empty, diagnosis.changed_since_last_visit_fact_ids must name the fact(s) that state it. Never leave any of these citation fields empty for a claim you decide to include -- a claim with no cited fact has nothing behind it and will not reach the patient.
```

The old sentence *"reason_for_visit and diagnosis items have no such field"* is deleted outright — it described the exact gap this PRD closes and would now be actively wrong. No other paragraph in the prompt (MERGE, LOW PRIORITY, QUESTIONS, PII, LANGUAGE RULES, STATUS, NOT STATED) references `reason_for_visit` or `diagnosis` by name, so no other edit is required. The `{schema}` placeholder already reflects whatever `_ASSEMBLE_SCHEMA` generates from the live `CarePlan` model (`_llm_schema(CarePlan, exclude={"terms", "note"})`), so once §4.2's model fields exist, the new `source_fact_ids`/`changed_since_last_visit_fact_ids` keys appear in the schema block the model sees automatically — no separate schema-string edit needed.

### 4.5 `backend/routes/worker.py` — `_strip_internal_provenance`

Current implementation (verified at HEAD):

```python
def _strip_internal_provenance(care_plan: dict) -> None:
    care_plan.pop("raw", None)
    care_plan.pop("summary_fact_ids", None)
    for _key in ("medications", "tests", "procedures", "other", "follow_up", "warning_signs"):
        for _item in care_plan.get(_key, []):
            _item.pop("source_fact_ids", None)
```

New — add `reason_for_visit` to the flat per-item loop (it is structurally identical to the six existing keys), and add a dedicated nested block for `diagnosis`, mirroring §4.3's production-code split between flat and nested handling:

```python
def _strip_internal_provenance(care_plan: dict) -> None:
    """Remove full raw artifacts and pipeline-internal evidence citations.

    ...(existing docstring, extended)...

    `diagnosis` is handled separately because its citation fields sit one
    level below `care_plan` (`diagnosis.details[].source_fact_ids`,
    `diagnosis.changed_since_last_visit_fact_ids`), not as a flat top-level
    per-item list like the other six (PRD 18 §4.3/§4.5).
    """
    care_plan.pop("raw", None)
    care_plan.pop("summary_fact_ids", None)
    for _key in ("reason_for_visit", "medications", "tests", "procedures", "other", "follow_up", "warning_signs"):
        for _item in care_plan.get(_key, []):
            _item.pop("source_fact_ids", None)
    _diagnosis = care_plan.get("diagnosis") or {}
    _diagnosis.pop("changed_since_last_visit_fact_ids", None)
    for _detail in _diagnosis.get("details", []):
        _detail.pop("source_fact_ids", None)
```

This runs on `output_data.get("care_plan", {})` at `worker.py:235`, exactly as today — no change to the call site, only to the function body. Every new field this PRD adds is internal provenance by the same reasoning PRD 01 §4.1 already established for `summary_fact_ids`/`source_fact_ids` generally: a fact-ID list is exactly as internal as the ledger it cites into, regardless of which field it lives on.

### 4.6 `low_priority` — decision: exempt, with reasoning recorded here for the first time

`low_priority: list[str]` receives content that started as a fully-mapped, already-categorized item (`assemble_and_render.txt`'s LOW PRIORITY rule: *"after mapping, move an item into low_priority (as one short line, not a full item)"*) and is then flattened to a bare string, discarding whatever citation the item would have carried had it stayed in its original section. This is, in shape, the same kind of gap this whole PRD closes — a patient-facing claim with no deterministic citation check.

**Decision: exempt, not covered, for this pass.** Reasoning:

1. **Stakes asymmetry, by the field's own definition.** `low_priority`'s prompt rule scopes it to *"a normal result, a routine finding, or an administrative detail: no action for the patient, and no diagnosis or plan they would want in the main sections."* By construction, this is the least clinically consequential content class in the entire schema — items are only eligible for demotion here because they are explicitly not a diagnosis, not a plan, and carry no action. This is categorically different from the failure mode motivating this PRD (an invented finding in a primary, un-collapsed "What the Doctor Found" card).
2. **The underlying fact was already checked once.** Every `low_priority` line originates from a `Fact` that already passed grounding's three deterministic fabrication checks (verbatim-substring quote verification, category validity, offset recovery — PRD 03 §4.3-§4.4) before the assembly LLM ever saw it. What is *not* independently re-verified is only whether the model's one-line demotion still faithfully reflects that fact — the same residual risk `summary` carries and that `summary_fact_ids` exists specifically to check. `low_priority` is the one place this residual risk is left to the LLM review pass alone, same as `questions` is left to the LLM review pass alone by explicit design (brief §2.5).
3. **The fix is not free, and lands on 08's territory.** Covering it properly requires a shape change — `list[str] -> list[LowPriorityItem]` where `LowPriorityItem` carries `text: str` and `source_fact_ids: list[int]` — which means a new Pydantic model, a prompt rewrite, a `_verify_assembly` extension (a fourth citation-check shape: flat-list-of-strings-with-companion-ids), a `_strip_internal_provenance` extension, *and* a frontend change: verified `CarePlanView.tsx:284-287` and `buildPdfHtml.ts:98-99` both render `low_priority` today as `result.low_priority.map((item) => <li>{item}</li>)` and `result.low_priority.map(item => \`<li>${escapeHtml(item)}</li>\`)` respectively — plain strings, not objects. That ripple crosses into 08's explicit territory for a content class this PRD's own stakes argument (point 1) puts at the bottom of the priority order.
4. **Not an unverifiable-self-report field either way.** Unlike PRD 14's rejected `merged: bool`, this decision doesn't add a field and then decline to trust it — it declines to add the field at all, for a documented reason, which is exactly the "well-argued exemption" the task scope invites rather than a silent gap.

This exemption is written down here, not left implicit, because an undocumented exemption is the precise failure mode this entire PRD exists to fix. The exemption stands as specified above; it is not being revisited now. It is recorded as conditionally revisitable (§9): if PRD 05 §7.5's review-catch-rate study is ever run and shows a materially worse miss rate on low-stakes, list-shaped content specifically, that finding is the trigger to reopen this decision — not a commitment to reopen it on any timeline.

### 4.7 Review and correct — confirmed, no code change required

Read `_resolve_path` (`pipeline.py:307`), `_PATH_SEGMENT_RE` (`pipeline.py:304`, `r"([a-zA-Z_][a-zA-Z0-9_]*)(\[(\d+)\])?"`), `_diff_item` (`pipeline.py:568`), and `_split_array_path` (`pipeline.py:545`) directly: none of them hardcodes a field allowlist. `_resolve_path` walks any dotted/indexed path against the live `CarePlan` dict structurally; `_diff_item` recurses through dicts and lists uniformly "at ANY nesting depth" (its own docstring); `_split_array_path`'s docstring explicitly names `"diagnosis.details"` as a path it already handles correctly (splitting on the *last* `.` specifically to support a dotted prefix). `review.txt`'s JOB 1 fidelity instructions ("Find every place the care plan says something its fact(s) do not support: an added diagnosis or interpretation...") are not scoped to any field list at all — they already cover `reason_for_visit` and `diagnosis` today, before this PRD, exactly as much as they cover the six checked fields. **Conclusion: no change to `review.txt`, `correct.txt`, `_resolve_path`, `_diff_item`, or `_verify_correction_diff` is needed.** The LLM-side review/correct loop already generically supports removing or correcting a bad `reason_for_visit[N]` or `diagnosis.details[N]` entry; what this PRD adds is the deterministic layer that catches what that non-fatal, unmeasured LLM pass might miss — the same relationship `_verify_assembly` already has with review/correct for the six originally-covered fields (PRD 04 §4.4's ownership note: "05 does not re-implement it").

### 4.8 Seam with PRD 13 (`why` nullability)

PRD 13 edits the same two files this PRD edits — `care_plan.py` and `assemble_and_render.txt` — for an unrelated field (`why` on `Medication`/`Test`/`Procedure`/`OtherInstruction`, made nullable). Stated seam assumptions, so either lands first without conflict:

- **`care_plan.py`**: PRD 13 adds a `field_validator("why", mode="before")` plus a `_blank_str_to_none` module function, touching only the four `why`-bearing classes. This PRD adds a new field (`source_fact_ids` / `changed_since_last_visit_fact_ids`) to three different classes (`ReasonForVisit`, `DiagnosisDetail`, `Diagnosis`) that PRD 13 does not touch at all (none of them has a `why` field). Zero class-body overlap between the two PRDs' edits — no merge conflict expected regardless of landing order.
- **`assemble_and_render.txt`**: PRD 13 rewrites the `NOT STATED --` paragraph only. This PRD rewrites the `MAPPING --` and `SOURCE_FACT_IDS --` paragraphs only. All three paragraphs are adjacent but textually independent (`NOT STATED` follows `SOURCE_FACT_IDS` follows `STATUS` follows `MAPPING` in the file's current order) — no shared sentence needs to satisfy both PRDs' requirements, matching the same "adjacent but independent" relationship PRD 13 §4.8 already documented with PRD 14's `MERGE` paragraph.
- **`_diff_item`/`_PII_ELIGIBLE_FIELDS`**: unaffected by either PRD's changes to these three classes — a new `list[int]` leaf compares by equality like any other unnamed leaf (never a string, so never PII-eligible), exactly as PRD 13 §4.8 already reasoned for a hypothetical `merged: bool`.

### 4.9 Test-fixture blast radius

Grepped `backend/tests/` for every direct constructor call to `ReasonForVisit(` or `DiagnosisDetail(`: **16 call sites across 4 files** (`test_jobs_e2e_scenarios.py`, `test_pipeline_assembly.py`, `test_pipeline_review.py`, `test_term_detection.py`). Contrast with PRD 12's ~45 construction sites for its `extraction_method` change: PRD 12's field was **required with no default**, so every one of those 45 sites needed an edit merely to keep constructing. This PRD's three new fields are all `default_factory=list` — **none of the 16 existing call sites requires any edit to keep compiling or constructing successfully.** The blast radius here is a fixture-completeness concern, not a compile-breakage one:

- `backend/tests/fixtures/care_plan.json` — round-trips through `test_care_plan_round_trips_full_fixture` via *strict* dict equality (`model.model_dump(mode="json") == full_fixture`, verified at `test_care_plan.py:21-24`). Adding a field with a default does not break construction, but **does** break this specific test, since the re-serialized model now carries three keys (`reason_for_visit[].source_fact_ids`, `diagnosis.details[].source_fact_ids`, `diagnosis.changed_since_last_visit_fact_ids`) the static fixture file doesn't have. Fix: add these three keys (small, non-empty, e.g. `[1]`) to the fixture's existing `reason_for_visit` and `diagnosis` blocks — same pattern PRD 01 §7.1 already used when it added `summary_fact_ids`/`source_fact_ids` to this same fixture.
- `frontend/src/tests/fixtures/realCarePlanOutput.fixture.json` — represents the *post-strip*, frontend-received shape. Confirmed no change needed: it already omits the six existing `source_fact_ids` fields (correctly, since they're stripped server-side) and must continue to omit these three new ones for the identical reason.
- The other 3 files (`test_jobs_e2e_scenarios.py`'s `_build_care_plan` helper, `test_pipeline_assembly.py`, `test_pipeline_review.py`, `test_term_detection.py`) construct these models via keyword arguments, not full-fixture dict validation — no edit required for existing tests to keep passing; new tests are added alongside them (§7).

## 5. API Change Summary

No externally-visible change. `summary_fact_ids` and `source_fact_ids` (on all eight item models, after this PRD) and `changed_since_last_visit_fact_ids` are, and remain, internal-only — stripped by `_strip_internal_provenance` before `output_data` is persisted or returned (§4.5). The internal `CarePlanInternal.care_plan` model gains three new keys that a caller inspecting Firestore's raw pipeline-internal state (never the API response) would see:

| Key | Before | After this PRD |
|---|---|---|
| `reason_for_visit[].source_fact_ids` | absent | added to the internal model; populated by assembly; filtered to real ledger ids; item dropped if left uncited (§4.3) — **stripped before the API response**, never present externally |
| `diagnosis.details[].source_fact_ids` | absent | same treatment, nested (§4.3) — **stripped**, never present externally |
| `diagnosis.changed_since_last_visit_fact_ids` | absent | added; populated whenever `changed_since_last_visit` is non-empty; the string is cleared to `""` if left uncited (§4.3) — **stripped**, never present externally |

No route signature, HTTP status, or error shape changes. `CarePlanContent`'s wire shape (what the frontend actually receives) is unchanged by this PRD.

**Downstream effect on PRD 14, noted for the record.** The two new per-item `source_fact_ids` fields (`ReasonForVisit`, `DiagnosisDetail`) also feed PRD 14's `merge_candidate_signal` log-only aggregate (its §4.4) for free — once this PRD lands, a diagnosis-category item citing more than one fact starts counting toward that aggregate the same way the six previously-covered item types already do. This PRD does not implement or alter `merge_candidate_signal` itself; the effect is a side benefit of closing the citation-existence gap for its own, unrelated reason.

## 6. Frontend Change Summary

**No TypeScript changes required.** Verified directly against `frontend/src/types/carePlan.ts`: the six existing `source_fact_ids` fields (on `Medication`, `Test`, `Procedure`, `OtherInstruction`, `FollowUp`, `WarningSign`) are correctly *absent* from every corresponding TS interface, because they are stripped server-side before the frontend ever receives a response (§4.5, and PRD 01 §6's original reasoning). The three new fields this PRD adds get the identical treatment — stripped at the same boundary, by the same function, before the wire response is built — so they must likewise be absent from `ReasonForVisit`'s TS interface (currently `{ reason: string; description: string }`, unchanged) and from `DiagnosisDetail`'s/`Diagnosis`'s TS interfaces (unchanged).

**One pre-existing inconsistency discovered while verifying this, unrelated to this PRD's own changes, flagged and assigned rather than silently ignored:** `frontend/src/types/carePlan.ts`'s `CarePlanContent` interface declares `summary_fact_ids: number[]` as a required (non-optional) field — but per `_strip_internal_provenance`, this key is *always* popped before the API response, meaning the TS type asserts a shape that is never true at runtime (the key is always absent, never present-with-an-empty-array). This predates this PRD and is not fixed here — it is **assigned to PRD 08 (frontend-and-pdf)**, which owns `carePlan.ts`. The concrete fix: delete `summary_fact_ids` from the `CarePlanContent` interface, matching how the six item-level `source_fact_ids` fields are already correctly omitted. Resolved in §9; not this PRD's file to edit.

**One bounded frontend change this PRD does specify** (overriding §3's "no frontend changes" Non-Goal for this one named case): when `_verify_assembly`'s new diagnosis block (§4.3) drops every entry in `diagnosis.details`, the "What the Doctor Found" card must still render and say so explicitly, rather than silently vanishing — silent disappearance reads to the patient as "nothing was found" instead of "we couldn't verify what was found." No new backend field or API signal is introduced; the frontend already receives everything it needs (`reason_for_visit`, `diagnosis.changed_since_last_visit`, `diagnosis.details`).

*`frontend/src/components/CarePlanView.tsx` (verified at HEAD, lines 162-187):*

- Current render guard (line 162): `result.diagnosis && result.diagnosis.details?.length > 0`.
- New render guard: `result.diagnosis && (result.diagnosis.details?.length > 0 || result.reason_for_visit?.length > 0 || !!result.diagnosis.changed_since_last_visit)` — the card now also renders when `details` is empty but there is other evidence of a visit (a populated `reason_for_visit`, or a non-empty `changed_since_last_visit`). When there is no evidence of a visit at all (`reason_for_visit` empty and `diagnosis.changed_since_last_visit` empty and `diagnosis.details` empty), the card still does not render — that case is unchanged.
- Inside the card, immediately after the existing `changed_since_last_visit` paragraph (lines 164-168) and before the details-mapping block, add: when `!result.diagnosis.details || result.diagnosis.details.length === 0`, render one paragraph in the same inline-style idiom as the `changed_since_last_visit` paragraph:
  ```tsx
  {(!result.diagnosis.details || result.diagnosis.details.length === 0) && (
    <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
      We couldn't confirm the specific findings from your note.
    </p>
  )}
  ```
  The existing `.map((det, i) => ...)` block over `sortedDetails` is otherwise unchanged — it simply renders zero items when `details` is empty, and the fallback paragraph above stands in for it.
- Exact fallback copy: **"We couldn't confirm the specific findings from your note."**

*`frontend/src/utils/buildPdfHtml.ts` (verified at HEAD, lines 38-51) — the printed/downloaded report's mirror of the same card:*

- Current render guard (line 38): `result.diagnosis && result.diagnosis.details?.length`.
- New render guard: `result.diagnosis && (result.diagnosis.details?.length || result.reason_for_visit?.length || result.diagnosis.changed_since_last_visit)` — same widened condition as the frontend card, for the same reason: the printed report must not silently drop the section either.
- Inside the block, after the existing `changed_since_last_visit` paragraph (lines 40-42) and before/in place of the `details.map(...)` (lines 43-49), add: when `!result.diagnosis.details?.length`, append the same fallback sentence instead of the (empty) mapped details markup:
  ```ts
  if (!result.diagnosis.details?.length) {
    diagnosis += `<p style="color:#6B7280;font-size:13px;margin:0 0 8px 0;">We couldn't confirm the specific findings from your note.</p>`;
  } else {
    diagnosis += result.diagnosis.details.map(det => /* unchanged existing template */ ...).join('');
  }
  ```
  Exact fallback copy is identical to the on-screen card's: **"We couldn't confirm the specific findings from your note."**

`frontend/src/types/carePlan.ts` is still not edited by this PRD — both changes above are render-logic and copy only, inside components that already receive every field they reference.

## 7. Testing

All new tests live under `backend/tests/care_plan/` (primarily `test_pipeline_assembly.py`) and `backend/tests/models/test_care_plan.py`, following the conventions PRD 04 §7 already established.

### 7.1 `backend/tests/models/test_care_plan.py`

- Update `backend/tests/fixtures/care_plan.json` (§4.9): add `source_fact_ids: [1]` to the fixture's `reason_for_visit[0]` and `diagnosis.details[0]` entries, and `changed_since_last_visit_fact_ids: [2]` alongside the fixture's existing non-empty `changed_since_last_visit` string (add one if the fixture's current value is `""`, so the round-trip actually exercises a non-empty case). `test_care_plan_round_trips_full_fixture` needs no code change once the fixture carries these keys.
- `test_reason_for_visit_source_fact_ids_defaults_to_empty_list` — construct `ReasonForVisit()` with no `source_fact_ids=`; assert `== []`.
- `test_diagnosis_detail_source_fact_ids_defaults_to_empty_list` — same pattern for `DiagnosisDetail()`.
- `test_diagnosis_changed_since_last_visit_fact_ids_defaults_to_empty_list` — same pattern for `Diagnosis()`.

### 7.2 `backend/tests/care_plan/test_pipeline_assembly.py` — extending the existing soundness test group

- Extend the existing parametrized `test_verify_assembly_enforces_source_fact_ids_on_every_item_type` to include `"reason_for_visit"` as a seventh case (it now fits the same flat mechanism — no special-casing needed in the test either).
- `test_verify_assembly_leaves_diagnosis_and_changed_since_last_visit_untouched_when_fully_cited` — a `CarePlan` with a `diagnosis.details` entry and a `changed_since_last_visit` value, both fully cited against the ledger; assert the returned `CarePlan.diagnosis` is unchanged (no-op path, mirrors the existing `test_verify_assembly_returns_same_object_when_no_correction_needed`).
- `test_verify_assembly_drops_diagnosis_detail_with_empty_source_fact_ids` — a `diagnosis.details[0]` with `source_fact_ids=[]`; assert it is absent from the result and `model.diagnosis.details` shrinks accordingly.
- `test_verify_assembly_drops_diagnosis_detail_with_all_hallucinated_source_fact_ids` — `source_fact_ids=[999]`, ledger has facts `1, 2`; assert dropped, not kept with an empty list.
- `test_verify_assembly_filters_partial_hallucination_on_diagnosis_detail_without_dropping_it` — `source_fact_ids=[1, 999]`, ledger has fact `1`; assert the detail survives with `source_fact_ids == [1]`.
- `test_verify_assembly_drops_all_diagnosis_details_leaves_empty_list` — every `diagnosis.details` entry uncited; assert the result's `diagnosis.details == []` (not that `diagnosis` itself is removed — `Diagnosis` is not optional on `CarePlan`).
- `test_verify_assembly_clears_uncited_changed_since_last_visit` — `changed_since_last_visit="Blood pressure has worsened."`, `changed_since_last_visit_fact_ids=[999]`, ledger has fact `1`; assert the result's `changed_since_last_visit == ""` and `changed_since_last_visit_fact_ids == []`.
- `test_verify_assembly_leaves_empty_changed_since_last_visit_unchecked` — `changed_since_last_visit=""`; assert no warning logged and no update applied, regardless of what `changed_since_last_visit_fact_ids` contains (proves the check is conditioned on the string being non-empty, not unconditionally run).
- `test_verify_assembly_filters_partial_hallucination_on_changed_since_last_visit` — `changed_since_last_visit_fact_ids=[1, 999]`, ledger has fact `1`; assert the string is preserved and the id list narrows to `[1]`.

### 7.3 `backend/tests/care_plan/test_pipeline_prompts.py`

- `test_assemble_prompt_mapping_lists_source_fact_ids_for_reason_for_visit_and_diagnosis` — assert the MAPPING section's `reason_for_visit ->` and `diagnosis ->` lines both contain `"source_fact_ids"`.
- `test_assemble_prompt_source_fact_ids_rule_no_longer_exempts_reason_for_visit_and_diagnosis` — regression guard: assert the literal substring `"reason_for_visit and diagnosis items have no such field"` does **not** appear in `_ASSEMBLE_PROMPT` (proves the old, now-false exemption sentence was actually deleted, not just supplemented).
- `test_assemble_prompt_names_changed_since_last_visit_fact_ids` — assert `"changed_since_last_visit_fact_ids"` appears in `_ASSEMBLE_PROMPT`.

### 7.4 `backend/tests/routes/test_worker.py`

Extend the existing `_strip_internal_provenance` test group (PRD 01 §7.3's `test_job_completed_output_has_no_summary_fact_ids` / `has_no_source_fact_ids` pattern):

- `test_job_completed_output_has_no_reason_for_visit_source_fact_ids` — mock a `care_plan` dict with `reason_for_visit: [{"reason": "...", "source_fact_ids": [1]}]`; assert `"source_fact_ids" not in saved_output_data["care_plan"]["reason_for_visit"][0]`.
- `test_job_completed_output_has_no_diagnosis_source_fact_ids` — `diagnosis: {"details": [{"title": "...", "source_fact_ids": [1]}], "changed_since_last_visit_fact_ids": [2]}`; assert both `"source_fact_ids" not in saved_output_data["care_plan"]["diagnosis"]["details"][0]` and `"changed_since_last_visit_fact_ids" not in saved_output_data["care_plan"]["diagnosis"]`.

### 7.5 Regression test: every `CarePlan` field must have a recorded soundness classification

This is the test item 7 of the task scope calls for by name — the mechanism that stops the next field added to `CarePlan` from silently repeating this exact gap. Add, alongside `_ITEM_LIST_FIELDS` in `pipeline.py`:

```python
# Every top-level CarePlan field must appear in exactly one of the three
# sets below (PRD 18 S7.5) -- this is what turns "a new field was added
# with no soundness decision" into a failing test instead of a silent gap,
# the exact failure mode this PRD exists to close for diagnosis/reason_for_visit.
_SOUNDNESS_CHECKED_FIELDS = frozenset(_ITEM_LIST_FIELDS) | {"diagnosis", "summary"}
_SOUNDNESS_EXEMPT_FIELDS = {
    "questions": "deliberately ungrounded by design (brief S2.5) -- PRD 18 S4.1",
    "low_priority": "demoted low-stakes content, LLM fidelity review only, no deterministic check -- PRD 18 S4.6",
    "terms": "glossary entries from a fixed reference wordlist, not a model-asserted clinical claim -- PRD 18 S4.1",
    "note": "upload metadata, never model output -- PRD 18 S4.1",
}
_SOUNDNESS_NOT_APPLICABLE_FIELDS = {"doc_type", "version", "summary_fact_ids"}
```

And, in `backend/tests/care_plan/test_pipeline_assembly.py`:

```python
def test_every_care_plan_field_has_a_soundness_classification():
    """Regression guard for PRD 18's headline gap: a field added to CarePlan
    with no soundness decision recorded must fail this test, not ship
    silently the way reason_for_visit/diagnosis did."""
    all_fields = set(CarePlan.model_fields)
    classified = (
        set(pipeline_module._SOUNDNESS_CHECKED_FIELDS)
        | set(pipeline_module._SOUNDNESS_EXEMPT_FIELDS)
        | set(pipeline_module._SOUNDNESS_NOT_APPLICABLE_FIELDS)
    )
    unclassified = all_fields - classified
    assert not unclassified, (
        f"{unclassified} added to CarePlan with no soundness decision recorded "
        f"-- see PRD 18 S4.1's audit table and S7.5's classification sets."
    )
```

- `test_soundness_checked_fields_all_carry_a_source_fact_ids_shape` — for every name in `_SOUNDNESS_CHECKED_FIELDS` other than `"diagnosis"`/`"summary"` (handled structurally differently), assert the corresponding item model declares `source_fact_ids` in `model_fields`; a companion assertion for `"diagnosis"` checks `DiagnosisDetail.model_fields` and `Diagnosis.model_fields` instead. This is the test that would have caught PRD 01's original six-model scoping gap had it existed then.

### 7.6 `frontend/src/tests/components/CarePlanView.test.tsx` — the "couldn't confirm" fallback (§6)

Follows the file's existing fixture-object convention (see the `summary: '', summary_fact_ids: [], reason_for_visit: [...], diagnosis: { details: [...] }` pattern already used throughout this file):

- `test('renders the "What the Doctor Found" card with the couldn\'t-confirm fallback when reason_for_visit is present but diagnosis.details is empty')` — fixture with `reason_for_visit: [{ reason: 'High blood pressure', description: '...' }]` and `diagnosis: { details: [] }`; assert the card renders (title "What the Doctor Found") and its body contains the text "We couldn't confirm the specific findings from your note." and does not attempt to render any detail item.
- `test('renders no "What the Doctor Found" card when there is no evidence of a visit')` — fixture with `reason_for_visit: []` and `diagnosis: { details: [] }` (and `changed_since_last_visit` empty/absent); assert no element with title "What the Doctor Found" is rendered — the unchanged no-evidence case.

A parallel pair of cases (same two fixtures) should be added to `frontend/src/tests/utils/buildPdfHtml.test.ts` asserting the generated HTML string contains the same fallback sentence in the `reason_for_visit`-present/`details`-empty case, and omits the "What the Doctor Found" section entirely in the no-evidence case.

## 8. Manual Intervention Required From You

- **Prompt smoke test against a real note with a diagnosis section**, once run via ngrok + pm2 (`SERVICE_MODE=combined`), consistent with PRD 04 §8 / PRD 03 §8's identical reasoning — none of this is automatable without a real Vertex AI call: (a) confirm `diagnosis.details[]` and `reason_for_visit[]` items in the pipeline's internal (pre-strip) output actually carry non-empty, plausible `source_fact_ids`, not just an empty list the deterministic guard then silently accepts as "nothing to drop"; (b) confirm a note that states something changed since the last visit produces a non-empty `changed_since_last_visit` *and* a non-empty `changed_since_last_visit_fact_ids` together, never one without the other; (c) deliberately feed a note where a diagnosis-category fact is ambiguous or borderline, and confirm the model's judgment about what belongs in `diagnosis.details` versus `low_priority` still tracks the LOW PRIORITY rule correctly now that `diagnosis.details` items also carry a citation obligation; (d) confirm the "What the Doctor Found" card still renders normally end-to-end for a well-behaved note (no attempted-but-uncited diagnosis silently vanishing when it shouldn't).
- No new environment variables, credentials, or console configuration — this PRD is schema + prompt + pure Python only, identical footprint in kind to PRD 04.

## 9. Open Questions & Decisions

- `[RESOLVED: ReasonForVisit and DiagnosisDetail each get source_fact_ids: list[int] = Field(default_factory=list), the identical shape PRD 01 already gave the six other item models.]` — closes the six-of-eight coverage gap identified in S4.1's audit; PRD 01's original exclusion was scoped by its task brief's "six models" list, not by a principled reason these two are different in kind.
- `[RESOLVED: Diagnosis.changed_since_last_visit gets a sibling changed_since_last_visit_fact_ids: list[int] = Field(default_factory=list), mirroring CarePlan.summary/summary_fact_ids's already-settled sibling-list shape.]` — this field is a latent instance of the same bug class (a trend-asserting clinical claim with zero citation surface), not a cosmetic gap; covering it costs one field and no shape change.
- `[RESOLVED: the diagnosis nested-container problem is solved with a second, dedicated block inside _verify_assembly, not a generalized nested-path descriptor.]` — mirrors _log_thin_fields' own existing precedent (flat loop + one dedicated diagnosis.details loop) for the identical reason: exactly one nested container exists on the schema, and an abstraction for N=1 case is unjustified speculative complexity.
- `[RESOLVED: dropping an unbacked diagnosis.details item reuses the exact drop-and-log mechanics _ITEM_LIST_FIELDS already applies to the six flat item lists; dropping an uncited changed_since_last_visit claim reuses correct.txt's own existing "set summary to \"\" -- no array position to delete" convention rather than inventing a second one.]`
- `[RESOLVED: a fully-emptied diagnosis.details IS special-cased -- the card no longer silently hides. CarePlanView.tsx's render guard widens to also fire on other evidence of a visit (reason_for_visit present, or diagnosis.changed_since_last_visit non-empty), and in that empty-details case the card renders the fallback sentence "We couldn't confirm the specific findings from your note." instead of the details list; buildPdfHtml.ts gets the identical guard and copy so the printed report matches. When there is no evidence of a visit at all, the card still does not render.]` — reason: silent disappearance of a diagnosis card reads to the patient as "nothing was found" rather than "we couldn't verify what was found," which is the wrong signal for a diagnosis specifically; no new backend field or API signal is required. Full specification in §6.
- `[RESOLVED: low_priority is exempted from the citation-existence check for this pass, with the four-point rationale recorded in S4.6 (stakes asymmetry by the field's own definition, the underlying fact already passed grounding-time checks, the fix crosses into 08's territory for a shape change, and this is a documented "don't add the field" decision rather than an unverifiable self-report the way PRD 14's merged: bool would have been).]` — the point of writing this down here is that it was never written down anywhere before.
- `[RESOLVED: review.txt, correct.txt, _resolve_path, _diff_item, and _verify_correction_diff require zero code changes -- all confirmed by direct inspection to already generically support nested paths including diagnosis.details[N], with no field allowlist anywhere in that machinery.]`
- `[RESOLVED: no TypeScript changes are needed in frontend/src/types/carePlan.ts -- the three new fields are stripped server-side before the API response, identically to the six existing source_fact_ids fields already correctly omitted from every TS interface.]`
- `[RESOLVED: a fully-emptied diagnosis.details renders the card with an explicit "We couldn't confirm the specific findings from your note." fallback instead of disappearing, whenever there is other evidence of a visit (reason_for_visit present, or diagnosis.changed_since_last_visit non-empty); with no evidence of a visit at all, the card still does not render.]` — decisive principle: always display something to the user when we can, and say so explicitly when we genuinely cannot confirm something, rather than silently omitting. No new backend field or API signal; a bounded frontend render-condition and copy change, specified concretely in §6 and covering both `CarePlanView.tsx` and `buildPdfHtml.ts`.
- `[DEFERRED: PRD 05 §7.5's LLM-review catch-rate evaluation protocol remains unrun.]` This PRD closes the deterministic gap for `reason_for_visit`/`diagnosis`/`changed_since_last_visit`; how often the non-fatal `review` step actually catches a fabrication is a genuinely unmeasured, project-wide gap, explicitly out of this PRD's scope, and already tracked under PRD 05. Recorded here as a known, named gap — not this PRD's to run or resolve.
- `[RESOLVED: §4.6's low_priority exemption stands as specified -- not revisited by this PRD.]` It remains conditionally revisitable: if PRD 05 §7.5's study is ever run and shows a materially worse miss rate on low-stakes, list-shaped content, that finding is the trigger to reopen it — not a commitment to reopen it on any timeline. §4.6's body text updated to match.
- `[RESOLVED: frontend/src/types/carePlan.ts's CarePlanContent.summary_fact_ids field is deleted from the interface -- assigned to PRD 08 (frontend-and-pdf), which owns that file, not fixed here.]` `_strip_internal_provenance` always pops this key before the API response, so the required TS field asserts a shape that is never true at runtime — the same treatment the six item-level `source_fact_ids` fields already correctly get (omitted, not required-then-always-absent). Recorded as a named hand-off to 08; §6 updated to match.
