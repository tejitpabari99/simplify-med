# PRD 07 — Glossary

Parent brief: `docs/agent_files/2026-09-09-docs-fidelity-concision-brief/brainstorm.v1.md` (approved; not re-litigated here — see especially the "Glossary" decision table and §3.8).
Branch: `docs/fidelity-concision-brief`.
Depends on: 01 (`backend/models/care_plan/care_plan.py` — `GlossaryTerm`, `CarePlan.terms`; unaffected by this PRD), 04 (its §9 flags the interface gap §4.4 below closes).
Depended on by: 06 (pipeline-orchestration: wires the background-thread submission described in §4.3 and consumes `render_care_plan_text` for the "after" readability score — §4.4), 08 (frontend: `renderTextWithTerms` already derives 100% of its highlighting from `CarePlan.terms`' keys — §6 — so nothing there changes code-side, but the *set* of keys this sub-project produces is exactly what gets highlighted).

## 1. Problem

Four independent defects sit in the glossary path today, verified against the real code:

- **The keying bug.** `build_terms_glossary` (`backend/utils/jargon_db.py:288`) keys the output dict on `hit["term"]` — the Michigan dictionary's canonical, possibly parenthesised or comma-listed term string — instead of `hit["matched_term"]`, the literal alias `lookup_medical_terms` (`jargon_db.py:213-231`) already threads through for exactly this purpose (the comment at `jargon_db.py:224` reads "Preserve the concrete alias variant that actually matched"). `renderTextWithTerms` (`frontend/src/components/CarePlanView.tsx:6-51`) does a plain, case-insensitive substring search of the rendered text against `Object.keys(terms)` — so a key that never appears verbatim in the body text highlights nothing. For the dictionary's 1,962 entries, every one whose canonical `term` field contains a parenthetical qualifier or a comma list (`"plaque (in an artery)"`, `"abdomen, abdominal"`) is affected: the glossary key is the full qualified string, the body text contains only the bare alias, and the two never match. `"heart"` happens to work only because its canonical form and its (only) alias are identical strings.
- **The dictionary is not a jargon list.** `michigan_medical_dictionary.json` is a general plain-language *health* dictionary; it defines `heart`, `blood`, `pain`, `brain`, `stomach`, `fever`, and `ability` ("To able to or can do.") — words no adult patient needs decoded. Once (A) is fixed, these entries will start correctly highlighting words a general reader already knows, trading one visible failure (nothing highlighted) for another (everything highlighted, most of it noise).
- **The dictionary has real gaps.** It has no entry at all for `calcified`, `contrast`, `angiogram`, `narrowing`, `circumflex`, `electrocardiogram`, or `statin` (verified by direct lookup — zero hits for any of the seven). No mechanical fix to the existing lookup surfaces these; something has to *propose* them.
- **The re-detection step has no input once the pipeline inverts.** `build_glossary_from_simplified_text` (`backend/utils/term_detection.py:77-107`) re-detects terms against `clarified` — a whole-document prose string produced by `clarify_and_action`. Both prose stages are deleted by the brief's architecture inversion (§2.5); assembly (04) returns a typed `CarePlan`, and no prose document exists downstream of it any more. PRD 04 §9 flags this explicitly as an interface gap for "06/07" and declines to resolve it, since 04's own return type (`CarePlan`, not `str`) is what exposes the gap. This PRD closes it.

## 2. Goals

- Fix the `matched_term`/`term` keying bug in `build_terms_glossary`, with regression coverage on a real parenthesised entry and a real comma-listed entry.
- Deterministically prune `michigan_medical_dictionary.json` against a common-word stoplist, as a one-time, reviewed, committed change to the data file — not a runtime filter.
- Add a glossary-curation LLM call that filters detected terms a general reader could already define and proposes terms the dictionary missed, each carrying a distinct, auditable `source`. Selection is criterion-based, with a soft cap as a backstop only.
- Define one rendered-text projection function — `render_care_plan_text(care_plan) -> str` — that both this sub-project's own re-detection and 06's "after" readability score consume, closing PRD 04 §9's gap.
- Specify the exact background-thread contract (inputs, outputs, failure mode) 06 wires into `iter_steps`, without wiring it myself.
- Full test coverage for all four fixes, including the two regression fixtures the task calls for by name.

## 3. Non-Goals

- No pipeline wiring. This PRD does not touch `care_plan/pipeline.py::iter_steps`, does not call `ThreadPoolExecutor`, and does not decide which call site issues `executor.submit(...)`. It specifies the function signature and behavior 06's submission wraps (§4.3, §9).
- No `CarePlan`/`GlossaryTerm`/`Fact` schema changes. `GlossaryTerm` (`{definition, source, imgUrl, altText}`) already has everything this PRD needs — `source` is an unconstrained `str`, not an enum, so a new value needs no schema change (verified: 01 PRD §7.1 already confirms `GlossaryTerm(source="notes")`-style construction is untouched by 01's enum deletions).
- No frontend code changes. `renderTextWithTerms`, `MedicalTerm`, and the "Medical Terms Glossary" card (`CarePlanView.tsx:335-346`) are 08's files. §6 specifies the contract 08's existing code already satisfies and what changes in the *data* it receives.
- No `Constants.Pipeline.PIPELINE_STEPS` changes, no step numbering. 06's territory.
- No new third-party dependency (no `nltk`, no `wordfreq`). The stoplist is a hand-curated, checked-in JSON file, matching the existing `abbreviations.json`/`sources.json` data-file convention — `backend/requirements.txt` has no NLP word-list library today and this PRD doesn't add one.
- No routing of model-proposed glossary definitions through 05's fidelity reviewer. See §9 for why this departs from a mitigation the brief's own open-risk table (§5) suggests.
- No changes to `lookup_medical_terms`, `_medical_rows`, or `inflected_aliases`/`term_aliases` (`text_normalization.py`). Verified correct as-is (§4.1) — the bug is entirely in the row built *from* their correct output, one function away.

## 4. Architecture Decisions

### 4.1 The bug fix — `backend/utils/jargon_db.py`

**Verification.** `inflected_aliases` and `term_aliases` (`backend/utils/text_normalization.py`) are correct: `term_aliases("plaque (in an artery)")` yields `["plaque (in an artery)", "plaque", "plaque in an artery"]`; `term_aliases("abdomen, abdominal")` yields `["abdomen", "abdominal"]`. `_medical_rows()` (`jargon_db.py:117-153`) builds one row per `(canonical_term, alias)` pair via `inflected_aliases`, and each row correctly carries both `"term"` (canonical, e.g. `"plaque (in an artery)"`) and `"matched_term"` (the alias, e.g. `"plaque"`) — the comment at line 224 is accurate. `lookup_medical_terms` (`jargon_db.py:213-231`) also behaves correctly: `seen`/`seen_terms` guarantee **at most one hit per canonical dictionary entry**, using whichever alias (longest-first) actually appears in the text — so `hit["matched_term"]` is always the literal substring present in the source text, by construction. The entire defect is contained in `build_terms_glossary` (`jargon_db.py:279-294`), which discards `matched_term` and keys on `term` instead.

**Fix:**

```python
def build_terms_glossary(medical_term_hits: list[dict]) -> dict[str, dict]:
    """
    Build the compact terms glossary dict for the final JSON output.
    Keys are the literal alias each hit matched in the source text
    (hit["matched_term"]), not the dictionary's canonical term — the
    frontend highlights by searching body text for these exact keys
    (CarePlanView.tsx:11,41), so the key must be a substring that can
    actually appear there. Callers must supply Michigan-shaped hits
    (lookup_medical_terms, curate_glossary_terms) where matched_term is
    always present; this is a KeyError, not a silent fallback, on any
    caller that violates that contract.
    """
    glossary: dict[str, dict] = {}
    for hit in medical_term_hits:
        # Last write wins if duplicate matched_term values appear in input hits.
        glossary[hit["matched_term"]] = {
            "definition": hit["definition"],
            "source": hit["source"],
            "imgUrl": hit.get("imgUrl"),
            "altText": hit.get("altText"),
        }
    return glossary
```

**Old → new, worked example** (`michigan_medical_dictionary.json` has two `plaque` entries — `"plaque (in an artery)"` and `"plaque (on teeth)"`; only one can ever be a hit per call, since `lookup_medical_terms`'s `seen` set is keyed by normalized alias and blocks the second canonical term the instant either claims `"plaque"`):

| | Old (keyed on `term`) | New (keyed on `matched_term`) |
|---|---|---|
| Text says "plaque" | key: `"plaque (in an artery)"` | key: `"plaque"` |
| `renderTextWithTerms` search | searches body for `"plaque (in an artery)"` → no match → **not highlighted** | searches body for `"plaque"` → match → **highlighted** |
| Glossary card heading | `"plaque (in an artery)"` (ugly, exposes internal disambiguation) | `"plaque"` (clean) |
| Text says "abdominal" | key: `"abdomen, abdominal"` | key: `"abdominal"` |
| Text says "heart" | key: `"heart"` | key: `"heart"` (unchanged — canonical and matched_term always coincide when the dictionary term has no comma/parenthetical) |

**Knock-on effect on deduplication.** The existing `"# Last write wins"` comment and behavior are preserved verbatim, just re-scoped from `term` to `matched_term`. This introduces no new collision risk within a single `lookup_medical_terms()` call: `seen`/`seen_terms` already guarantee at most one hit per canonical term, and each surviving hit's `matched_term` corresponds 1:1 to a distinct `normalized_term` that won the `seen` race — no two hits from one call can share a `matched_term` value. A collision becomes possible only if a caller merges hit lists from separate detection passes (this PRD introduces exactly one such merge — §4.3's curated + proposed list) or if two independent dictionary entries happen to generate an identical literal alias string across canonical terms (not observed in the current 1,962-entry file). "Last write wins" is the same deliberate, pre-existing policy in both cases; nothing new needs to be decided, only re-confirmed.

**Public rename, needed for §4.3.** `_get_source_name` (`jargon_db.py:49-55`) becomes public `get_source_name`, since `curate_glossary_terms` (a new function in a different module, `term_detection.py`) needs to resolve the new `llm_proposed` source name (§4.5) the same way every other source is resolved — through `sources.json`, not a hardcoded string. No behavior change, just drop the leading underscore and update the two in-module call sites.

### 4.2 Deterministic stoplist prune

**Decision: prune the committed file, not a runtime filter.** The approved brief's own decision-log wording — "Deterministic one-time prune of `michigan_medical_dictionary.json`" — names the artifact, not a load-time layer, and this matches the global "mutate in place, no versioning" constraint applied at the data-file level: a permanent runtime filter is itself a small piece of always-on version-skew machinery this codebase's other decisions argue against. It is also the *safer* choice for the brief's own named risk ("the stoplist may strip a term that is jargon in clinical context"): a load-time filter reapplies an old, unreviewed decision forever, including to any future re-scrape of the source dictionary; a one-time prune forces a human to look at the diff (§8) each time the source file changes, rather than trusting a blocklist written once to still be correct against content nobody has re-examined. Runtime cost of *not* filtering is also genuinely zero — `_medical_rows()` is `lru_cache`d and loads the (now smaller) file once per process regardless.

**New script: `backend/scripts/prune_jargon_stoplist.py`** (matches the existing `backend/scripts/cleanup_anonymous_users.py` precedent — a one-off, checked-in, re-runnable maintenance script, not part of the request-serving app):

```python
"""One-time, re-runnable prune of michigan_medical_dictionary.json against
common_word_stoplist.json. Rerun this whenever the source dictionary is
refreshed from https://medicaldictionary.lib.umich.edu/ -- do not apply the
stoplist at load time (see PRD 07 SS4.2); every prune is a reviewed, committed
diff, never a silent runtime filter.

A record is dropped only if EVERY comma-separated branch of its canonical
`term` is in the stoplist. A term with a parenthetical qualifier
("plaque (in an artery)") is NEVER dropped, regardless of its bare form --
the qualifier itself is evidence the entry captures a specific clinical
sense a bare stoplist word does not (verified: no such record exists in the
current file where the bare, paren-stripped form is also a stoplist word).
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "jargon"

def _branches(term: str) -> list[str]:
    return [p.strip().lower() for p in term.split(",")]

def prune(dictionary: list[dict], stoplist: set[str]) -> tuple[list[dict], list[dict]]:
    kept, dropped = [], []
    for record in dictionary:
        term = record["term"]
        if "(" in term:
            kept.append(record)
            continue
        if all(branch in stoplist for branch in _branches(term)):
            dropped.append(record)
        else:
            kept.append(record)
    return kept, dropped

if __name__ == "__main__":
    dictionary = json.loads((DATA_DIR / "michigan_medical_dictionary.json").read_text())
    stoplist = set(json.loads((DATA_DIR / "common_word_stoplist.json").read_text()))
    kept, dropped = prune(dictionary, stoplist)
    print(f"Dropping {len(dropped)} of {len(dictionary)} records:")
    for record in dropped:
        print(f"  {record['term']!r}: {record['definition'][:70]!r}")
    (DATA_DIR / "michigan_medical_dictionary.json").write_text(
        json.dumps(kept, indent=2) + "\n"
    )
```

**New data file: `backend/data/jargon/common_word_stoplist.json`** — a flat JSON array of lowercase words, kept in the repo *after* the prune runs (not consulted at runtime) so the exact input to a past prune is auditable and the script is re-runnable against a future dictionary refresh without reconstructing the list from scratch. A verified starter list, built by checking candidate everyday words against the actual dictionary (14 real matches found this way, beyond the brief's own 7 named examples):

```json
["heart", "blood", "pain", "brain", "stomach", "fever", "ability",
 "fatigue", "control", "medicine", "treatment", "symptom", "risk",
 "foot, feet"]
```

This starter list is deliberately not exhaustive — building the complete, defensible ~100-300 word list the brief's "1,962-entry plain-language health dictionary" framing implies is a data-curation pass, not something to hand-author blind inside a PRD. `foot, feet` is flagged as borderline (very basic anatomy, but arguably more concrete/useful to a patient than `ability` or `control`) for the human review in §8, rather than silently included or excluded here.

### 4.3 The glossary curation LLM call

**Contract.** A single new free function, alongside the existing detectors, in `backend/utils/term_detection.py` — not a method on `CarePlanPipeline`. It must be a free function (mirroring the existing `score_text_safe(text, "before")` background-thread precedent at `services/care_plan_pipeline.py:51`) because 06 submits it directly to a `ThreadPoolExecutor`, and it needs its own `LLMClient` instance rather than sharing `CarePlanPipeline._llm` across a thread boundary with the pipeline's own sequential ground/assemble/review/correct calls.

```python
def curate_glossary_terms(
    source_text: str,
    detected_terms: list[dict],
    llm_client: LLMClient | None = None,
) -> list[dict]:
    """Filter + propose pass over the deterministically detected, stoplist-
    pruned Michigan terms (brief SS3.8 step 2). Depends only on the raw
    source text and detect_terms' own output -- not on anything ground(),
    assemble_and_render(), review(), or correct() produce -- so 06 can
    submit it to a background thread immediately after detect_terms
    completes, in parallel with the rest of the pipeline. Must never raise:
    a curation failure falls back to the deterministic list untouched,
    the same fail-open posture every other detector in this module uses.

    Returns a list shaped identically to lookup_medical_terms() hits, so
    downstream code (build_glossary_from_care_plan, build_terms_glossary)
    treats curated and proposed entries exactly like deterministic ones.
    """
    try:
        client = llm_client or LLMClient()
        prompt = _CURATE_PROMPT.format(
            max_terms=_CURATION_PROPOSAL_HINT,
            detected_terms_block=_format_detected_terms_for_curation(detected_terms),
            source_text=source_text,
        )
        raw = client.generate_json(
            prompt, temperature=Constants.Llm.TEMPERATURE_JSON, max_tokens=Constants.Llm.MAX_TOKENS
        )
        if not isinstance(raw, dict):
            raise ValueError(f"expected dict, got {type(raw)}")
        drop = {str(d).strip().lower() for d in raw.get("drop", [])}
        propose = raw.get("propose", [])
    except Exception:
        logger.exception("curate_glossary_terms: curation call failed - keeping detected terms unfiltered")
        return detected_terms

    kept = [t for t in detected_terms if t["term"].strip().lower() not in drop]
    existing = {t["matched_term"].strip().lower() for t in kept}
    normalized_source = normalize_text(source_text)

    proposed_hits = []
    for item in propose:
        matched_term = str(item.get("matched_term", "")).strip()
        definition = str(item.get("definition", "")).strip()
        if not matched_term or not definition or matched_term.lower() in existing:
            continue
        # Deterministic guard: a proposed term must actually be a substring
        # of the note. A model that "proposes" a word not in the source
        # cannot have extracted it -- cannot be a real finding.
        if not contains_normalized_term(normalized_source, normalize_text(matched_term)):
            continue
        existing.add(matched_term.lower())
        proposed_hits.append({
            "term": matched_term,
            "matched_term": matched_term,
            "definition": definition,
            "source": get_source_name("llm_proposed"),
            "imgUrl": None,
            "altText": None,
            "action": "preserve_define",
        })

    combined = kept + proposed_hits
    if len(combined) > _CURATION_TOTAL_BACKSTOP:
        logger.warning(
            "curate_glossary_terms: truncating %d total terms to backstop %d",
            len(combined), _CURATION_TOTAL_BACKSTOP,
        )
        overflow = len(combined) - _CURATION_TOTAL_BACKSTOP
        proposed_hits = proposed_hits[: max(0, len(proposed_hits) - overflow)]
        combined = kept + proposed_hits
    return combined
```

`_CURATION_PROPOSAL_HINT = 15` (model-facing hint, not enforced) and `_CURATION_TOTAL_BACKSTOP = 40` (code-enforced, covering `kept + proposed_hits`) are deliberately different numbers, mirroring PRD 04 §4.4's `questions` pattern (prompt instruction primary, code truncation backstop only). Truncation cuts `proposed_hits` first, never `kept`: entries that survived both the dictionary lookup and the LLM's own filter are higher-confidence than a raw proposal.

**Why proposed entries also get `term == matched_term`.** A proposed entry has no separate "canonical dictionary form" — the literal string the model found *is* the term, the same bug-fix principle as (A): the glossary key must be a substring that actually appears in the text.

**New prompt file: `backend/care_plan/prompts/curate_glossary.txt`:**

```
You are curating a plain-language glossary for a patient reading their own
care plan. You are given a clinical note and a list of terms a dictionary
lookup flagged as possible medical jargon in that note.

Do two things:

1. FILTER -- from the DETECTED TERMS list below, identify any term a general
adult reader, with no medical background, could already define correctly
without help. List those under "drop". Do not drop a term just because the
word itself is common if its clinical sense here is specific and
non-obvious -- for example, "plaque" is an everyday word, but its meaning
here (a fatty buildup in an artery) is not something a general reader
already knows, so it should NOT be dropped.

2. PROPOSE -- read the note for medical jargon that is NOT in the detected
list at all, most likely because the dictionary does not contain it. For
each one, write a short, plain-language definition a patient could
understand, in one or two sentences, in the style of the DEFINITION
EXAMPLES below. Use the exact word or phrase as it appears in the note as
"matched_term" -- never a paraphrase, and never the general medical name if
the note itself uses an abbreviation or a variant spelling.

CRITERION -- for both jobs, keep or propose a term only if a general reader
could plausibly NOT already define it correctly. This is a judgement call,
not a word-length or word-frequency rule: do not drop a short or ordinary-
looking word whose meaning here is specific, and do not keep or propose a
technical-looking word a patient would in fact already understand from
context. Do not aim for a fixed count -- propose as many or as few terms as
the note genuinely warrants. If you find yourself proposing more than
{max_terms}, keep only the {max_terms} least likely for a general reader to
already know.

DEFINITION EXAMPLES (style to match):
- "calcified" -> "Hardened by a buildup of calcium, which can happen in
  blood vessels or tissue over time."
- "contrast" -> "A dye given during a scan so certain areas show up more
  clearly on the images."
- "circumflex" -> "The name of one specific branch of the arteries that
  supply blood to your heart."

DETECTED TERMS (term: definition):
{detected_terms_block}

CLINICAL NOTE:
{source_text}

Return JSON only, matching this schema. No markdown, no commentary.
{"drop": ["<term>", ...], "propose": [{"matched_term": "<exact word or phrase from the note>", "definition": "<one or two plain sentences>"}]}

JSON OUTPUT:
```

**Budget.** `temperature=Constants.Llm.TEMPERATURE_JSON` (0.2, matches every other structured-JSON pipeline call). `max_tokens=Constants.Llm.MAX_TOKENS` (8,192, the default, not `MAX_TOKENS_LONG_FORM`) — this call emits a short drop-list plus a handful of short definitions, not a whole `CarePlan`.

**Failure classification: non-fatal, self-contained.** The function catches its own exceptions (§ body above) and never raises — there is no `iter_steps` fatal/non-fatal wrapping decision for 06 to make here at all, unlike `ground()`/`assemble_and_render()`. This matches the brief's framing of curation as a background enhancement, not a required pipeline stage.

### 4.4 CLOSING THE INTERFACE GAP — the rendered-text projection

**One projection, both consumers.** A single new function, `render_care_plan_text(care_plan: CarePlan) -> str`, lives in `backend/utils/term_detection.py` (co-located with its first consumer, `build_glossary_from_care_plan`, immediately below). 06 imports it directly for the second consumer — the "after" readability score, replacing `score_text_safe(event.clarified, "after")` (`services/care_plan_pipeline.py:106`) with `score_text_safe(render_care_plan_text(event.care_plan), "after")` once `PipelineRunResult.clarified` no longer exists.

Both consumers want the same thing — "the text a patient actually reads, in the order they read it" — matching the brief's own resolution of the readability-scoring risk (§5: "Score the rendered care plan's own text... it measures what the patient actually reads"). Glossary re-detection needs every string a term could appear in, case-insensitively; readability scoring needs natural sentence/paragraph structure. One raw (non-lowercased) projection serves both: the glossary consumer normalizes it at the point of use, the readability consumer scores it as-is. Two field lists kept in sync by hand is a worse drift risk than one function two callers trust.

```python
def render_care_plan_text(care_plan: "CarePlan") -> str:
    """Every patient-visible text field on a CarePlan, concatenated in the
    eight-card frontend's top-to-bottom order (brief SS3.10), one field
    value per paragraph (blank-line separated) so paragraph/sentence-
    boundary-sensitive consumers -- utils/scoring.py:186's paragraph split
    and its ^-anchored MULTILINE regexes -- don't merge unrelated fields
    into one run-on unit.

    Two consumers: (1) build_glossary_from_care_plan below, re-detecting
    against the FINAL corrected output (brief SS3.7); (2) 06's "after"
    readability score, replacing event.clarified once the prose stages are
    deleted (brief SS2.5; the gap PRD 04 SS9 flags, closed here).

    Excludes: doc_type/version (schema plumbing), status/severity/urgency
    (typed enums, not free text), note (internal, zero frontend consumers),
    summary_fact_ids (ints), and terms itself (built FROM this text).
    """
    parts: list[str] = []

    def add(value) -> None:
        if value:
            parts.append(value)

    add(care_plan.summary)
    for r in care_plan.reason_for_visit:
        add(r.reason); add(r.description)
    add(care_plan.diagnosis.changed_since_last_visit)
    for d in care_plan.diagnosis.details:
        add(d.title); add(d.plain_name); add(d.description); add(d.what_it_means_for_you)
    for m in care_plan.medications:
        add(m.title); add(m.plain_name); add(m.why); add(m.dosage)
        add(m.frequency); add(m.timing); add(m.duration)
        add(m.instructions); add(m.side_effects_to_watch); add(m.change)
    for t in care_plan.tests:
        add(t.title); add(t.plain_name); add(t.why); add(t.description); add(t.preparation)
    for p in care_plan.procedures:
        add(p.title); add(p.plain_name); add(p.why); add(p.what_to_expect); add(p.timeframe)
    for o in care_plan.other:
        add(o.title); add(o.why)
        for step in o.steps:
            add(step)
        add(o.description); add(o.frequency); add(o.duration)
    for f in care_plan.follow_up:
        add(f.description); add(f.time_frame)
    for w in care_plan.warning_signs:
        add(w.symptom); add(w.what_it_might_mean); add(w.what_to_do); add(w.related_to)
    for q in care_plan.questions:
        add(q)
    for item in care_plan.low_priority:
        add(item)

    return "\n\n".join(parts)
```

Field order and membership are derived directly from `CarePlanView.tsx`'s own `withTerms(...)` call sites (`CarePlanView.tsx:145-330`), which is today's authoritative list of "what the patient reads," minus `diagnosis.main_conclusion` (deleted by 01) and re-sequenced into the brief's new eight-card order (§3.10) rather than the current 13-card layout, since that is the order 08 will actually render once it lands.

**Replaces `build_glossary_from_simplified_text`:**

```python
def build_glossary_from_care_plan(
    care_plan: "CarePlan",
    detected_terms: list[dict],
) -> dict[str, dict]:
    """Re-detect terms against the FINAL corrected CarePlan (brief SS3.7 /
    SS3.8 step 3). `detected_terms` is curate_glossary_terms' output
    (curated + proposed), not the raw deterministic hits -- curation has
    already finished on its background thread by the time correct() (05)
    returns, well before this runs."""
    normalized_text = normalize_text(render_care_plan_text(care_plan))
    found_terms = []
    for term in detected_terms:
        lookup_aliases = [term.get("matched_term") or term["term"], *inflected_aliases(term["term"])]
        if any(contains_normalized_term(normalized_text, normalize_text(alias)) for alias in lookup_aliases):
            found_terms.append(term)
    return build_terms_glossary(found_terms)
```

Logic is unchanged from today's function — only the input type changes (`CarePlan` instead of a prose `str`), by routing it through `render_care_plan_text` first.

### 4.5 `backend/data/jargon/sources.json`

New entry, so model-proposed definitions carry a distinct, resolvable `source` (task requirement, and the brief's stated mitigation for "model-proposed glossary definitions are unsourced clinical content" — §5, distinct-`source` half only, see §9 for the other half):

```json
{
  "id": "llm_proposed",
  "name": "Proposed by the glossary curation model (not from a fixed dictionary)",
  "fileName": null,
  "link": null,
  "description": "Generated for medical jargon the dictionary did not contain. Not verified against a fixed reference source; kept identifiable and auditable via this distinct source label.",
  "notes": "Distinct from every dictionary-backed source so unsourced definitions never masquerade as one."
}
```

### 4.6 Module wiring summary (for 06's reference)

| Symbol | File | Status |
|---|---|---|
| `build_terms_glossary` | `utils/jargon_db.py` | fixed (§4.1) |
| `get_source_name` | `utils/jargon_db.py` | renamed public (was `_get_source_name`) |
| `michigan_medical_dictionary.json` | `data/jargon/` | pruned, committed (§4.2) |
| `common_word_stoplist.json` | `data/jargon/` | new (§4.2) |
| `sources.json` | `data/jargon/` | +1 entry (§4.5) |
| `prune_jargon_stoplist.py` | `scripts/` | new, one-time/re-runnable (§4.2) |
| `curate_glossary_terms` | `utils/term_detection.py` | new (§4.3) |
| `curate_glossary.txt` | `care_plan/prompts/` | new (§4.3) |
| `render_care_plan_text` | `utils/term_detection.py` | new (§4.4) |
| `build_glossary_from_simplified_text` | `utils/term_detection.py` | **deleted**, replaced by `build_glossary_from_care_plan` (§4.4) |

## 5. API Change Summary

No HTTP-visible schema shape changes — `CarePlan.terms: dict[str, GlossaryTerm]` is untouched at the type level. What changes is the *content* the pipeline produces within that shape:

| Behavior | Before | After this PRD |
|---|---|---|
| Glossary keys | canonical dictionary `term` (may contain `(...)`/`, `) | the literal `matched_term` alias found in text |
| Highlighting for parenthesised/comma-listed entries | silently broken (key never matches body text) | works — same substring the highlighter searches for |
| `heart`, `blood`, `pain`, `brain`, `stomach`, `fever`, `ability`, and similar | present, highlighted once (A) is fixed | absent (pruned by the stoplist, §4.2) |
| `calcified`, `contrast`, `angiogram`, `narrowing`, `circumflex`, `electrocardiogram`, `statin` | absent (no dictionary entry) | present when the note contains them, `source: "llm_proposed"` |
| Glossary size | driven purely by dictionary hits | driven by dictionary hits minus LLM-filtered common words, plus LLM-proposed gaps, backstopped at 40 total |
| Re-detection input | `clarified: str` (whole-document prose) | `care_plan: CarePlan` via `render_care_plan_text` |

## 6. Frontend Change Summary

**No code change required in 08's files.** `renderTextWithTerms` (`CarePlanView.tsx:6-51`) already derives every highlighting decision purely from `Object.keys(terms)` against rendered body text — it has no separate "is this term interesting enough" logic of its own. Because this PRD controls exactly which strings become keys in `CarePlan.terms`, the criterion in §4.3 (drop-if-a-general-reader-would-know-it, propose-if-genuinely-jargon) automatically governs inline highlighting with no additional signal from 07 to 08: **the glossary card and the highlighted spans are two views of the same dict, and this PRD owns the dict.**

What 08 should be aware of, as a data-shape note rather than a required code change:

- Glossary keys are now lowercase, literal-alias strings (`"plaque"`, `"abdominal"`) rather than the dictionary's Title-Case-ish canonical forms. `CarePlanView.tsx:340`'s `<span className="glossary-term">{term}</span>` renders the raw key — 08 may want to capitalize it for display (e.g., `term[0].toUpperCase() + term.slice(1)`), a cosmetic call left to 08, not required for correctness.
- `GlossaryTerm.source` may now be `"Proposed by the glossary curation model (not from a fixed dictionary)"` in addition to the two existing dictionary source names. If 08 ever renders `source` to the patient (it does not today — `CarePlanView.tsx:341` only renders `definition`), a model-proposed entry should not be visually indistinguishable from a dictionary-backed one; not required by this PRD, noted for awareness.
- Glossary size is now variable and typically smaller for a routine note, larger for a jargon-dense one — no fixed expectation to code against.

## 7. Testing

### 7.1 `backend/tests/utils/test_jargon_db.py` — fix + extend

Existing `TestBuildTermsGlossary` tests construct hit dicts without `matched_term`; they must be updated to include it (they exercise `build_terms_glossary` directly, and its new contract requires the key):

- `test_builds_dict_from_hits`, `test_last_write_wins_for_duplicates`: add `"matched_term"` to every fixture dict (equal to `"term"` here, since neither exercises alias-divergence).
- **New, load-bearing regressions** (task's named requirement):
  - `test_build_terms_glossary_keys_on_matched_term_not_term` — hits with `term="plaque (in an artery)"`, `matched_term="plaque"`; assert `"plaque" in glossary` and the parenthesised string is not a key.
  - `test_lookup_medical_terms_plaque_in_artery_matches_bare_alias` — end-to-end through `lookup_medical_terms(normalize_text("heavy plaque was seen"))` against the real dictionary; assert `matched_term == "plaque"` regardless of which of the two `plaque` canonical entries wins the tie-break (unrelated, existing behavior).
  - `test_build_terms_glossary_abdomen_abdominal_keys_on_matched_alias` — hits with `term="abdomen, abdominal"`, `matched_term="abdominal"`; assert `"abdominal" in glossary`, the comma-joined string is not.
  - `test_get_source_name_is_public` — `from utils.jargon_db import get_source_name`; assert it resolves `"michigan_medical_dictionary"` identically to today's `_medical_rows()` (regression guard for the §4.1 rename).

### 7.2 New: `backend/tests/scripts/test_prune_jargon_stoplist.py`

- `test_prune_drops_records_whose_every_branch_is_stoplisted` — synthetic 3-record dictionary (`"heart"`, `"plaque (in an artery)"`, `"abdomen, abdominal"`), stoplist `{"heart"}`; assert only `"heart"` is dropped.
- `test_prune_never_drops_a_parenthetical_term` — stoplist deliberately includes `"plaque"` (bare, paren-stripped); assert `"plaque (in an artery)"` still survives — proves the exemption in §4.2 is enforced in code, not just true by data coincidence.
- `test_prune_keeps_record_if_any_branch_survives` — `"abdomen, abdominal"` against stoplist `{"abdomen"}` only; assert the record is kept whole, not edited or dropped.
- `test_committed_dictionary_excludes_named_stoplist_examples` — loads the real, post-§8-review dictionary; assert none of `heart`, `blood`, `pain`, `brain`, `stomach`, `fever`, `ability` remain as bare canonical terms — guards against a future dictionary refresh silently skipping the review step.

### 7.3 `backend/tests/utils/test_term_detection.py` — extend

- `test_render_care_plan_text_includes_summary_and_medication_fields` — assert `summary` and a medication's `why` both appear, in that relative order.
- `test_render_care_plan_text_excludes_internal_fields` — `note` set, `summary_fact_ids` populated; assert neither leaks into the projection.
- `test_render_care_plan_text_is_deterministic` — call twice on the same input; assert identical output.
- `test_render_care_plan_text_joins_fields_as_separate_paragraphs` — assert `"\n\n"` between two distinct field values, guarding `utils/scoring.py`'s paragraph regex against a future `" "`-join regression.
- `test_build_glossary_from_care_plan_finds_term_in_diagnosis_but_not_medications` — a jargon term appears only in `diagnosis.details[0].description`; assert the glossary still finds it (proves the full projection feeds re-detection, not just `summary`).
- `test_curate_glossary_terms_falls_back_on_llm_failure` — stub `LLMClient.generate_json` raises; assert the result equals the input `detected_terms` unchanged, no exception propagates.
- `test_curate_glossary_terms_drops_named_common_word` — stub returns `{"drop": ["heart"], "propose": []}`; assert the `heart` hit is absent, others preserved.
- `test_curate_glossary_terms_proposes_new_term_found_in_source` — stub returns a `circumflex` proposal, `source_text` contains it; assert a hit with `matched_term == "circumflex"` and `source == get_source_name("llm_proposed")`.
- `test_curate_glossary_terms_rejects_proposed_term_not_in_source` — same stub, `source_text` doesn't contain it; assert it's dropped (§4.3's substring guard).
- `test_curate_glossary_terms_backstop_truncates_proposed_before_kept` — 35 kept + 10 proposed; assert exactly 40 survive and all 35 kept entries are among them.

### 7.4 Files checked and confirmed unaffected

- `backend/tests/utils/test_text_normalization.py` — no changes to `term_aliases`/`inflected_aliases`/`normalize_text`/`contains_normalized_term`; verified correct in §4.1.
- `frontend/src/tests/components/ResultScreen.test.tsx` — no frontend code change means no test change, though its fixture (08's `realCarePlanOutput.fixture.json`) will eventually need regenerating against real pipeline output — same division of labor 01 §7.1 already established.

## 8. Manual Intervention Required From You

- **Review the stoplist prune's diff before it is treated as final.** Run `backend/scripts/prune_jargon_stoplist.py`, read its printed drop list (every dropped `term` + its first 70 characters of definition), and confirm none of them is jargon in a clinical context the tool didn't anticipate — this is the brief's own named open risk, and no automated check can substitute for a human reading ~15-30 short lines once. Pay particular attention to `foot, feet` (§4.2), flagged as borderline.
- **Extend `common_word_stoplist.json` beyond the 14-word verified starter list** in §4.2 if the review in the previous bullet surfaces more everyday words worth pruning — this PRD deliberately did not hand-author an exhaustive list.
- **Prompt smoke test against 2-3 real or de-identified notes**, once 06 wires `curate_glossary_terms` into the live pipeline (ngrok + pm2, `SERVICE_MODE=combined`): confirm (a) a genuinely common word detected by the dictionary gets dropped; (b) a note containing one of the seven named gap-terms (`calcified`, `contrast`, `angiogram`, `narrowing`, `circumflex`, `electrocardiogram`, `statin`) gets it proposed, with a plain-language definition and `source: "llm_proposed"`; (c) the proposed term's `matched_term` actually appears verbatim in the rendered care plan text, so it highlights in the UI once 08 lands — not just in the glossary card. None of this is automatable without a real Vertex AI call and a judgement read of the output.
- No new environment variables, credentials, or console configuration.

## 9. Open Questions & Decisions

- `[RESOLVED: build_terms_glossary keys on hit["matched_term"], a strict dict access (KeyError on a malformed caller), not a defensive .get(...) fallback.]` — every real caller (lookup_medical_terms, build_glossary_from_care_plan's re-detection, curate_glossary_terms' proposed entries) is verified to always set matched_term; failing loudly on a future caller that doesn't is more useful than silently reproducing the original bug for that caller.
- `[RESOLVED: the Michigan dictionary is pruned as a committed, one-time, reviewed file change, not filtered at load time.]` — see §4.2's full justification: matches the brief's own wording, matches the "mutate in place" global constraint, and is the safer choice against the brief's own named risk of over-pruning, since it forces a human look at every future dictionary refresh rather than silently reapplying an old blocklist.
- `[RESOLVED: the stoplist prune drops a record only if every comma-branch of its canonical term is stoplisted, and never drops a record whose term contains a parenthetical qualifier at all.]` — verified against the real file that no parenthetical entry's bare form is also a plausible stoplist word today; the rule is enforced in code (tested in §7.2), not just true by data coincidence, so it stays safe if that ever changes.
- `[RESOLVED: curate_glossary_terms is a free function in utils/term_detection.py, not a CarePlanPipeline method, and constructs its own LLMClient when none is injected.]` — mirrors the score_text_safe background-thread precedent and avoids sharing CarePlanPipeline._llm across the thread boundary with the pipeline's own sequential calls.
- `[RESOLVED: curate_glossary_terms reads the ORIGINAL source text, not the corrected CarePlan, and is not fed back into assemble_and_render's preserve_and_define_terms.]` — it starts on a background thread right after detect_terms, before assemble_and_render begins, so the corrected CarePlan can't be its input, and 04's already-settled signature takes preserve_and_define_terms from detect_terms, not from here. A proposed term surviving into final text isn't guaranteed by an explicit "preserve" instruction — it's checked, not assumed, by build_glossary_from_care_plan's re-detection (§4.4), exactly the brief's own mechanism ("a term whose sentence was rewritten drops out automatically" — SS3.7). Re-detection is the safety net by design, not a missing piece.
- `[RESOLVED: model-proposed glossary definitions are NOT routed through 05's fidelity reviewer, despite the brief's SS5 open-risk table suggesting exactly that as a mitigation.]` — the approved Glossary decision-log table (not to be re-litigated) resolves this differently: only "a distinct source value," no reviewer pass, and the background-thread architecture (SS3.1; task item C: "depends only on the detected terms, not on anything the reviewer produces") is built so curation never blocks on or feeds review()/correct(). Routing through the reviewer would reintroduce the exact serialization the thread avoids, for content that's supplementary (a definition, not a clinical claim) and already auditable via its distinct source tag. Flagged explicitly since it's a real tension between two brief-adjacent documents, not silently picked.
- `[RESOLVED: 06 decides the exact ThreadPoolExecutor.submit(curate_glossary_terms, ...) call site, but term_data is only visible inside care_plan/pipeline.py::iter_steps, not at the services/care_plan_pipeline.py adapter layer where before_score's submission lives — so this call's site is necessarily different, not identical to that precedent.]` — the before_score pattern only proves the general shape (submit early, `.result()` late), not the specific location.
- `[RESOLVED: render_care_plan_text serves both consumers unmodified — one function, not two.]` — both want "what the patient reads, in reading order," differing only in whether the caller normalizes afterward — a one-line call-site difference, not a reason to fork the field list.
- `[OPEN: whether including short, non-sentence label fields (titles, dosage strings, timeframes) as their own "paragraphs" measurably skews the readability score's sentence-length statistics versus the old whole-document prose.]` — not resolvable without a real pipeline run scoring real before/after pairs (06's territory once wired). If a skew surfaces, the fix is narrowing the field list to prose-only fields for the readability consumer specifically, reopening the "one projection or two" question above. Deferred rather than guessed at.
- `[DEFERRED: the exact size of common_word_stoplist.json beyond the 14-word verified starter list is a data-curation task, not a design decision — see SS8.]`
- `[DEFERRED: whether 08 capitalizes glossary keys for card-heading display is a frontend cosmetic call, not gated on by this PRD landing.]`
