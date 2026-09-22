# PRD 10 — Numeric Integrity

Parent brief: `docs/agent_files/2026-09-09-docs-fidelity-concision-brief/brainstorm.v1.md`; this sub-project implements R2 and R3 of `docs/agent_files/2026-09-09-docs-fidelity-concision-brief/comparison-drive-research-bundle.v1.md` §5 (see also §4.4, §4.6).
Branch: `docs/fidelity-concision-brief`.
Depends on: 01 (`backend/models/ledger.py` — `Fact{id, category, unit_id, char_start, char_end, text}`, `quote_for()`; `backend/models/care_plan/care_plan.py` — the six item models' `source_fact_ids`), 03 (grounding's `Fact.text` semantics — clause granularity, may expand an abbreviation, must never invent a number — `ground.txt` lines 10-11, verified below), 04 (`_verify_assembly`, `assemble_and_render.txt`, the `_style_rules.txt` extraction), 05 (`correct.txt` also consumes the shared `_STYLE_RULES` constant, PRD 05 §4.4 — this PRD's prompt change reaches both call sites).
Depended on by: none currently — a leaf sub-project in this batch. PRD 11 (omission-signal) edits the same file (`pipeline.py`) in the same neighborhood (inside/around `_verify_assembly`'s sibling checks) for an unrelated signal (coverage, not numeracy); §4.7 below states the shared-file seam explicitly so the two land without stepping on each other.

## 1. Problem

`_verify_assembly` (`backend/care_plan/pipeline.py:394+`) runs three deterministic guards on the assembled `CarePlan`, and **all three are about citation existence only**: `questions` truncated to 3; `summary_fact_ids` filtered to real ledger ids; each item's `source_fact_ids` filtered to real ids, with a fully-unbacked item dropped. Grep confirms this is the entire deterministic surface: `grep -n "def _verify_assembly" -A 60 backend/care_plan/pipeline.py` shows the questions-cap block, the `summary_fact_ids` filter, and the `_ITEM_LIST_FIELDS` loop — nothing else. **Nothing checks that a number inside a rendered field survived rendering intact.** An item that correctly cites fact 47 and renders its dose as "250 mg" when fact 47's `text` says "25 mg" passes every check in that function: the citation resolves, the id is real, the item is kept.

The prompt side has the same gap. `backend/care_plan/prompts/_style_rules.txt` (loaded once as `_STYLE_RULES`, injected into both `assemble_and_render.txt` and `correct.txt` — confirmed by `grep -n "style_rules=_STYLE_RULES" backend/care_plan/pipeline.py`, two hits, lines 747 and 809) contains exactly one numeric rule:

```
- Never invent a number, and never convert vague wording ("a few weeks") into an exact one ("3 weeks") unless a fact states the exact number.
```

That covers fabrication-from-nothing and vague-to-exact conversion. It says nothing about rounding an already-exact value, converting a unit, adding a reference range, labeling a bare value normal/abnormal/elevated, attaching a severity or color to a number, or reframing a percentage as a frequency (or the reverse) — every one of which is a plausible, plausible-*looking* rendering choice a model asked to "render every field in plain language" (`assemble_and_render.txt` line 3, step 3) can make without ever inventing a value out of nothing, and none of which the existing rule forbids.

The only thing standing between a mangled number and the patient today is the review LLM call, and it is a weak backstop by the project's own account: non-fatal by design (PRD 05 §4.8 — "a failed review ships assembly's unchecked output"), documented in the brief's own cited literature as prone to rubber-stamping (arXiv:2310.08118 — 38 of ~92 invalid plans approved), and its catch rate has never been measured (PRD 05 §7.5's injected-error protocol is specified but still unrun, confirmed: no `manual_reviewer_catch_rate.py` file exists in the repo — `find backend -iname "*catch_rate*"` returns nothing).

This sub-project closes both gaps: a prompt-level rule that names every interpretive addition the model must not make to a number (R2), and a deterministic, model-free check that catches a number that drifted anyway (R3) — the second one working *because* the first one can't be trusted alone, exactly the same "deterministic gates precede and outrank LLM judgment" philosophy already governing every other guard in this file.

## 2. Goals

- Extend the shared style-rules text (`backend/care_plan/prompts/_style_rules.txt`) with an explicit `NUMERACY` block, in the house prompt voice, forbidding: an added normal/abnormal/elevated/low/high label on a bare value; an added reference range; rounding or truncating an already-exact number; a unit conversion; a percentage-to-frequency (or reverse) reframe; an attached severity/urgency/color the fact doesn't itself grade. It must explicitly permit copying a value+unit verbatim (with only the spacing/spelling changes the LANGUAGE RULES already allow) and permit an interpretation only when the fact itself already states it.
- A deterministic, model-free numeric-parity check, `_check_numeric_parity`, that runs at the end of `_verify_assembly` against the already citation-filtered `CarePlan`: for every free-text field of every surviving item (and for `summary`), tokenize numbers-with-units out of the rendered text and out of the `text` of every fact the item cites; log (never mutate, never drop) any number that appears in the item but in none of its cited facts.
- A precisely specified tokenizer: what counts as a number (integer, decimal, fraction, range, thousands-separated), what normalization is allowed (spacing/case around a unit, leading zeros, trailing decimal zeros), and an explicit, justified policy for the two known false-positive sources named in the task — a legitimate word-only rewrite ("BID" → "twice a day") and a legitimate token-changing rewrite (a date reformatted from "4/12" to "April 12").
- Named, documented, tunable constants (module-level, `_UPPER_SNAKE`, "reasoned, not calibrated" — matching `_QUOTE_MIN_LENGTH`/`_QUOTE_LONG_WORD_MIN_LENGTH`'s precedent, PRD 03 §4.3) and a logging shape that respects the file's existing PHI-adjacent guard (§4.4 below).
- Prompt-content regression tests for the `NUMERACY` block (PRD 04 §7.2's style) plus unit tests for the tokenizer and the parity check on fixtures.

## 3. Non-Goals

- **No release gate, no hold/abstain disposition, no patient-facing surface.** Per this batch's locked instruction, every signal this PRD adds is log-only. A numeric mismatch is logged and the item ships exactly as assembled — this is a deliberate, disclosed residual risk (§9), not an oversight.
- **No fifth LLM call.** The parity check is pure Python, runs synchronously inside `_verify_assembly`, and costs no additional model round-trip.
- **No protected-field registry, hazard reason codes, or S0–S3 severity scale** (rejected explicitly by the source comparison doc §6, "over-built for this product" — there is no release controller in this codebase to consume that classification).
- **No change to `assemble_and_render`'s or `iter_steps`'s signature.** `_verify_assembly(model, facts)` already receives everything this check needs (§4.3 explains why `units` is deliberately not threaded in). `_STEP`/`Constants.Pipeline.PIPELINE_STEPS` is untouched — this PRD adds no new pipeline step; it strengthens an already-wired one.
- **No change to `ground()` or `_verify_ledger`** (03's territory) — this PRD does not attempt to verify that grounding's `Fact.text` is itself numerically faithful to the source note; see §9 for the deferred, bounded gap this leaves, owned by PRD 03.
- **No omission/coverage logic.** PRD 11's territory — see §4.7 for the explicit shared-file seam.
- **No frontend changes.** Nothing in `output_data`, the API response shape, or `CarePlanView.tsx` changes.
- **No new `ErrorCode` members.** The check never raises; there is nothing to classify as fatal or non-fatal because there is no failure mode beyond "logged."
- **No full date/time-equivalence resolver** (month-name↔number mapping, AM/PM arithmetic, DD/MM vs. MM/DD disambiguation). §4.2 names this explicitly as disproportionate engineering for a log-only signal and takes the cheaper, disclosed-blind-spot alternative instead.

## 4. Architecture Decisions

### 4.1 The `NUMERACY` block — placement decision and text

**Decision: add it to the shared `_style_rules.txt`, not a separate block confined to `assemble_and_render.txt`.** The task raised this as an open call because the file is shared with `correct.txt`, so the question is whether a corrector-only exposure to the numeracy rules is harmless, neutral, or actively wrong. It is actively wrong to *omit* it from `correct.txt`: `correct.txt`'s own instructions (PRD 05 §4.4) tell the corrector, for a `"correct"` op, to take the reviewer's value "taken directly from the fact" and "re-render [it] in the same style as the rest of this document — e.g. if the given value is raw clinical shorthand, render it the way this document already renders comparable values (units, abbreviation expansion...)." That is a rendering step over a fact-sourced numeric value — structurally the identical operation `assemble_and_render` performs, run by a second, separate LLM call that is just as capable of quietly adding "(elevated)" or rounding "25 mg" while "restyling" it. Duplicating the block into `correct.txt` instead of sharing it would recreate exactly the drift risk PRD 05 §4.4 already named and rejected ("Duplicating that text into correct.txt would let the two drift on the next prompt edit"). `review.txt` never consumes `_STYLE_RULES` at all (confirmed: `grep -n "style_rules" backend/care_plan/prompts/review.txt` returns nothing) — the reviewer only reads and reports, never renders — so the shared placement reaches exactly the two call sites that render text and none that don't.

Proposed diff to `backend/care_plan/prompts/_style_rules.txt` — a new paragraph inserted between the existing `PII` paragraph and the `LANGUAGE RULES` bullet list (same structural prominence as `PII`, since it needs several negative examples rather than one bullet), plus one added clause on the existing numeric bullet pointing at it:

```
PII -- replace every person's name and every facility's name with a generic form: a clinician's name becomes "your doctor" (or "your surgeon" / "your cardiologist" / etc. if the fact itself names that specialty); a hospital or clinic name becomes "the hospital" or "the clinic." Example: "Doctor Alok Singh" becomes "your doctor." This is the one case where you do not preserve a fact's exact wording -- a generic form loses the patient no clinical information. The patient's own name, date of birth, address, and insurance details must never appear either.

NUMERACY -- a number is the easiest place to silently add a judgement the source never made, so give every one in this document the same verbatim discipline PII gets for names, plus one allowance: copy a value and its unit exactly as the fact states them ("A1c 7.2%" stays "your A1c was 7.2%"), changing only spacing or spelling the way LANGUAGE RULES below already permits ("metoprolol 25mg" -> "metoprolol 25 mg" is fine; the number and the unit itself are not). Never add a normal/abnormal/elevated/low/high label to a bare value unless the fact itself uses that word -- a fact giving "blood pressure 158/96" is a number, not a verdict; do not write "high blood pressure" for it unless a fact says so. Never add a reference range that isn't in the fact -- "A1c 7.2%" does not become "A1c 7.2% (normal range 4.0-5.6%)." Never round, truncate, or otherwise adjust an already-exact number -- "ejection fraction 42%" stays "42%," never "about 40%" or "40%." Never convert a unit -- "creatinine 1.4 mg/dL" stays mg/dL, never becomes a value you compute yourself in µmol/L. Never reframe a percentage as a frequency or a frequency as a percentage -- "occurs in 30% of patients" does not become "happens 3 out of 10 times you take it," and "taken twice daily" does not become "100% compliance." Never attach a severity, urgency, or color ("critical," "dangerously high," "mild") to a number the fact does not itself grade. You may add an interpretation of a number ONLY when the fact itself already states that interpretation in its own words -- a fact reading "A1c 7.2%, indicating poor control" may carry "indicating poor control" into the rendered field, because the source made that judgement, not you.

LANGUAGE RULES -- apply to every field you write:
- Active voice. Address the patient as "you."
- One idea per sentence. Keep sentences under about 20 words.
- Expand every abbreviation. Never print "BID", "HTN", "f/u", or similar -- use the plain words.
- Never invent a number, and never convert vague wording ("a few weeks") into an exact one ("3 weeks") unless a fact states the exact number -- see NUMERACY above for the rest of this document's numeric rules.
- Never add urgency, prognosis, or medical advice beyond what a fact states.
- Start every patient action (in medications, tests, procedures, other, follow_up) with a clear verb: Take / Call / Schedule / Ask / Bring / Watch / Avoid / Continue / Stop.
```

No change to `assemble_and_render.txt` or `correct.txt` themselves — both already consume `_STYLE_RULES` verbatim via the `{style_rules}` placeholder (PRD 05 §4.4), so this is purely additive text in one file, reaching both prompts automatically the same way the original `LANGUAGE RULES`/`PII` text already does.

### 4.2 The tokenizer — `_extract_number_tokens`

Lives in `backend/care_plan/pipeline.py`, next to `_verify_assembly` and its existing constants (`_QUOTE_MIN_LENGTH` et al.), following the same "same-file call, not an import" precedent PRD 04 §9 already established for reusing PRD 03's constants.

**What counts as a number.** Four shapes, in this precedence order: thousands-separated (`1,000` / `1,000.5`), a slash pair (`1/2`, `158/96` — ambiguous between fraction, ratio/BP reading, and date; disambiguated below), a hyphen range (`5-10`, `5.5-10.2`), or a plain integer/decimal (`25`, `7.2`). A number may be followed, with zero or one space, by a unit word — `%` alone, or a letter followed by up to 14 more letters/`%`/`/` (covers `mg`, `mL`, `mmHg`, `mg/dL`, `bpm`, `%`). `_UNIT_WORD_MAX_LENGTH = 15` is named and reasoned, not derived: long enough for the longest realistic compound lab unit (`mmol/L`, `mIU/mL`), short enough that it can't silently swallow the start of the next clinical word if a unit is missing:

```python
_UNIT_WORD_RE = r"%|[A-Za-z][A-Za-z%/]{0,14}"

_NUMBER_TOKEN_RE = re.compile(
    r"""
    (?P<num>
        \d{1,3}(?:,\d{3})+(?:\.\d+)?        # 1,000 or 1,000.5
      | \d+/\d+                             # fraction OR ratio/date shape: 1/2, 158/96, 4/12
      | \d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?   # range: 5-10, 5.5-10.2
      | \d+(?:\.\d+)?                       # plain integer or decimal
    )
    [ ]?
    (?P<unit>""" + _UNIT_WORD_RE + r""")?
    """,
    re.VERBOSE,
)
```

**What normalization is allowed.** Exactly the incidental-formatting differences the style rules explicitly *permit* elsewhere in this same file — `assemble_and_render.txt` line 6's own worked example is "metoprolol 25mg BID" → "metoprolol 25 mg twice a day," i.e., attached-vs-space-separated unit spacing is a sanctioned style change, not a value change:

```python
def _normalize_number(raw: str) -> str:
    """Canonicalize one bare number's own digits -- leading zeros, thousands
    separators, and a trailing decimal zero are formatting, not value, per
    the same principle assemble_and_render.txt's own worked example applies
    to unit spacing ("25mg" -> "25 mg" is a style change). Called on each
    component of a range/fraction separately, never on the whole thing."""
    raw = raw.replace(",", "")
    if "." in raw:
        integer_part, _, frac_part = raw.partition(".")
        frac_part = frac_part.rstrip("0")
        integer_part = integer_part.lstrip("0") or "0"
        return f"{integer_part}.{frac_part}" if frac_part else integer_part
    return raw.lstrip("0") or "0"
```

A unit word is compared lowercased, with the attached-vs-spaced difference already collapsed by the regex's optional single space; `"25mg"` and `"25 mg"` produce the identical token `("25", "mg")`. Deliberately **not** normalized: the number itself. `"25"` and `"250"` are different tokens — that difference is the entire point of this check.

**Known false-positive source 1 (given): a word-only rewrite introduces no digit.** "BID" → "twice a day" contains no digit on either side; `_extract_number_tokens("twice a day")` returns the empty set, nothing to compare, no possible false positive. No special-casing needed — this falls out of the tokenizer for free.

**Known false-positive source 2 (given, "the gnarliest bit"): a date reformatted from "4/12" to "April 12" changes tokens on purpose.** This is real: `4/12` is a slash pair, syntactically identical to a fraction (`1/2`) and to a ratio reading (`158/96`); a legitimate LANGUAGE RULES-driven rewrite to "April 12" keeps only one digit (`12`) and drops the other (`4`) entirely, which a naive parity check would read as "the item contains 12 and 4 is missing" or worse, "12 doesn't match any cited fact's tokens" once the slash-pair token `("4/12", "")` no longer exists on either side to align against.

**Decision: exclude date- and time-shaped spans from the token set on *both* sides of the comparison, rather than build date-equivalence resolution.** The rejected alternative — parse a written month name back to a number, handle "Apr" vs. "April," resolve `4/12` as either April-12 or 4-over-12, do the same for a time like "7:30 AM" — is real engineering for a signal this batch's own charter says must stay log-only; getting date-equivalence *wrong* (an ambiguous DD/MM vs. MM/DD read) would generate more false positives than it removes. The chosen alternative accepts a disclosed blind spot instead: a genuinely corrupted date (`4/12` → `4/21`) is not caught by this check. That trade is deliberate — a corrupted dose or lab value is a materially higher-consequence error than a corrupted follow-up date, and this check exists specifically for the former (§1).

The disambiguating rule that makes this work without a whitelist of "date words": **a slash pair or bare digit pair is treated as a date/time candidate, and excluded, only when nothing unit-shaped sits next to it.** `158/96 mmHg` (blood pressure) and `1/2 tablet` both have a trailing unit word and are kept as real values; a bare `4/12` with nothing else around it, or a written `April 12`, or a bare `7:30`, have no unit and are dropped:

```python
_TIME_OF_DAY_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
_BARE_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b(?![ \t]*[A-Za-z%])")
_MONTH_NAMES = (
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
)
_WRITTEN_DATE_RE = re.compile(
    r"\b(?:" + "|".join(_MONTH_NAMES) + r")\.?\s+\d{1,2}(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)

def _excluded_spans(text: str) -> list[tuple[int, int]]:
    """Date/time-shaped spans, dropped from BOTH sides of every numeric-
    parity comparison (PRD 10 §4.2's disclosed blind spot -- see there for
    why). _BARE_DATE_RE's negative lookahead is what lets a unit-bearing
    slash pair ("158/96 mmHg", "1/2 tablet") fall through untouched --
    only a slash pair with nothing unit-shaped after it is excluded."""
    spans = [m.span() for m in _TIME_OF_DAY_RE.finditer(text)]
    spans += [m.span() for m in _BARE_DATE_RE.finditer(text)]
    spans += [m.span() for m in _WRITTEN_DATE_RE.finditer(text)]
    return spans


def _extract_number_tokens(text: str) -> set[tuple[str, str]]:
    """Tokenize every number-with-optional-unit out of `text` into a set of
    (normalized_number, normalized_unit) pairs; unit is "" when none is
    attached. Excludes date/time-shaped spans entirely (see above)."""
    excluded = _excluded_spans(text)
    tokens: set[tuple[str, str]] = set()
    for m in _NUMBER_TOKEN_RE.finditer(text):
        if any(m.start() >= s and m.end() <= e for s, e in excluded):
            continue
        num, unit = m.group("num"), (m.group("unit") or "").lower()
        if "/" in num:
            num_norm = "/".join(_normalize_number(p) for p in num.split("/"))
        elif "-" in num:
            num_norm = "-".join(_normalize_number(p.strip()) for p in num.split("-"))
        else:
            num_norm = _normalize_number(num)
        tokens.add((num_norm, unit))
    return tokens
```

**Other named false-positive/negative sources, disclosed rather than solved (see §9):**
- A standalone ordinal day-of-month with no adjacent month name ("on the 12th") is not specially excluded and could false-positive; accepted as-is, with no evidence it occurs in the app's note distribution (§9).
- If `assemble_and_render.txt` were ever changed to instruct numbered `steps[]` prefixes ("1. Take..."), that would introduce spurious digit tokens; it does not today (verified: no numbering instruction anywhere in `assemble_and_render.txt`), so not defended against pre-emptively — whoever changes that prompt owns updating this check (§9).

### 4.3 The comparison basis: `Fact.text`, not `quote_for()` — and why `units` is deliberately not threaded in

The task calls this out as a real design decision, since `_verify_assembly` currently receives only `facts`, not `units`. Two candidate anchors exist for "what did the source actually say": `Fact.text` (grounding's own plain-clinical-shorthand paraphrase of the clause, already on every `Fact`) and `quote_for(fact, units_by_id)` (the verbatim excerpt, rehydrated on demand from the cited `Unit`'s raw text — `backend/models/ledger.py:70-81`).

**Decision: compare against `Fact.text`.** Three independent reasons converge on this:

1. **It is exactly what assembly was given.** `_format_facts_for_prompt` (`pipeline.py:334-347`) is the *only* view of a fact the `assemble_and_render` prompt ever receives — one line per fact, `f"[{fact.id}] {category}: {fact.text}"`. The model never sees `quote` or the raw `Unit.text` at all. This check's entire purpose (§1) is "did rendering preserve what assembly itself was handed" — checking the model's output against the model's own documented input is the tightest, correctly-scoped comparison for that question. Checking against `quote_for()` would audit a different, adjacent question — "did grounding's paraphrase preserve the source" — which is PRD 03's already-landed territory (verbatim-quote verification, `_is_verbatim_quote`), not this PRD's.
2. **`quote_for()` is provably too narrow a search space to be the primary comparison basis.** `ground.txt` line 10 describes `quote` as "a short, VERBATIM excerpt" while line 11 requires `text` to keep "every clinical detail (dose, frequency, timing, condition, quantity, site) named in the source" — i.e., `quote` is explicitly permitted to be shorter than the full clause `text` represents. A fact whose `text` is "Take metoprolol 25 mg twice daily for 30 days" could legitimately have `quote` = `"metoprolol 25mg"` (enough to be informative and locatable per `_is_informative_quote`, PRD 03 §4.3) without ever including "30." Anchoring the parity check on `quote_for()` alone would flag the item's legitimately-rendered "30 days" as unbacked purely because the grounding model chose a short quote — a **false positive built into the design**, not a tunable edge case.
3. **The obvious mitigation (fall back to the full cited `Unit.text` instead of the narrow quote) trades one false-positive risk for a false-negative one.** A `Unit` is one line (PRD 02); a single line can carry more than one fact (e.g., two medications comma-separated on one line, each with its own dose, each citing the same `unit_id`). Checking against the *whole* unit's text would make a dose legitimately swapped between two same-line facts invisible — the wrong number would still be "present" somewhere in the unit, just attached to the wrong drug. `Fact.text`, being per-fact, does not have this cross-contamination problem: it was already resolved (by the grounding model) to exactly the content of the one clause this fact represents.

Because the comparison anchor is `Fact.text`, no signature change is needed anywhere: `_verify_assembly(model, facts)` already has `facts`, and `assemble_and_render`/`iter_steps` are untouched. This is also why the check activates the moment this PRD lands — `_verify_assembly` is already wired into the live pipeline (unlike PRD 05's `review`/`correct`, which needed PRD 06 to call them at all).

**`[DEFERRED]`, recorded rather than pursued:** using `quote_for()` (with `units` threaded through) as a *second*, additional layer — one that would also catch a numeric error introduced by grounding itself (a plausible OCR/paraphrase misread inside `Fact.text` that `_is_verbatim_quote` never checks against, since that check only verifies `quote` is verbatim, not that `text`'s numbers match `quote`'s numbers) — is a real idea, but it requires exactly the wiring and the short-quote-coverage fix named above, and there is no evidence yet that grounding-introduced numeric drift is an observed problem distinct from assembly-introduced drift. See §9.

### 4.4 The check itself, and its logging shape

Runs at the end of `_verify_assembly`, after the citation-existence guards (`_ITEM_LIST_FIELDS`, `summary_fact_ids`) have already produced the final `updates`-applied model — so every item this check sees already has `source_fact_ids` filtered to real, resolvable ledger ids; a hallucinated id cannot inflate an item's backing set.

Fields checked are every free-text field of the six item models plus `summary`/`summary_fact_ids` — hand-enumerated, matching this file's existing `_RICHNESS_CHECKS` precedent (PRD 04 §9: "04 does not define a parallel set of constants... same-file call") rather than introspecting the schema, so what's covered is auditable at a glance rather than implicit:

```python
_NUMERIC_PARITY_FIELDS: dict[str, tuple[str, ...]] = {
    "medications": ("title", "plain_name", "why", "dosage", "frequency",
                     "timing", "duration", "instructions",
                     "side_effects_to_watch", "change"),
    "tests": ("title", "plain_name", "why", "description", "preparation"),
    "procedures": ("title", "plain_name", "why", "what_to_expect", "timeframe"),
    "other": ("title", "why", "description", "frequency", "duration"),  # steps[] handled separately
    "follow_up": ("time_frame", "description"),
    "warning_signs": ("symptom", "what_it_might_mean", "what_to_do", "related_to"),
}


def _check_numeric_parity(model: CarePlan, facts: list[Fact]) -> None:
    """R3 (PRD 10 §4.3/§4.4): log-only, model-free check that every number
    a rendered field states was present in at least one fact the item
    cites. Never mutates or drops anything -- unlike the citation-existence
    guards above it, a numeric mismatch has no safe deterministic repair
    (which side is right is exactly the judgement call this check cannot
    make), so logging is this PRD's entire, LOCKED contract."""
    facts_by_id = {f.id: f for f in facts}
    mismatches = 0

    def _backing_tokens(fact_ids: list[int]) -> set[tuple[str, str]]:
        tokens: set[tuple[str, str]] = set()
        for fid in fact_ids:
            fact = facts_by_id.get(fid)
            if fact is not None:
                tokens |= _extract_number_tokens(fact.text)
        return tokens

    def _check_field(field: str, index: int | str, attr: str, value: str,
                      backing: set[tuple[str, str]], num_cited: int) -> int:
        if not value:
            return 0
        backing_numbers = {num for num, _unit in backing}
        found = 0
        for num, unit in _extract_number_tokens(value):
            if (num, unit) in backing:
                continue
            found += 1
            if num in backing_numbers:
                logger.warning(
                    "assemble_and_render: numeric parity -- %s[%s].%s has a "
                    "value matching a cited fact's number but with a "
                    "different or missing unit (unit=%r)",
                    field, index, attr, unit,
                )
            else:
                logger.warning(
                    "assemble_and_render: numeric parity -- %s[%s].%s "
                    "contains a number not found in any of its %d cited "
                    "fact(s)", field, index, attr, num_cited,
                )
        return found

    for field, attrs in _NUMERIC_PARITY_FIELDS.items():
        for index, item in enumerate(getattr(model, field)):
            backing = _backing_tokens(item.source_fact_ids)
            num_cited = len(item.source_fact_ids)
            for attr in attrs:
                mismatches += _check_field(field, index, attr, getattr(item, attr, ""), backing, num_cited)
            if field == "other":
                for step_idx, step in enumerate(item.steps):
                    mismatches += _check_field(field, index, f"steps[{step_idx}]", step, backing, num_cited)

    if model.summary:
        mismatches += _check_field("summary", "-", "summary", model.summary,
                                    _backing_tokens(model.summary_fact_ids),
                                    len(model.summary_fact_ids))

    if mismatches:
        logger.warning(
            "assemble_and_render: numeric parity check flagged %d mismatch(es) "
            "in this care plan", mismatches,
        )
```

Wired at the very end of `_verify_assembly`:

```python
def _verify_assembly(model: CarePlan, facts: list[Fact]) -> CarePlan:
    ...  # existing three guards, building `updates`
    result = model.model_copy(update=updates) if updates else model
    _check_numeric_parity(result, facts)   # PRD 10 R3 -- log-only, never mutates `result`
    return result
```

**Logging shape — deliberately excludes the raw digits, matching this file's existing PHI-adjacent guard.** `_log_thin_fields` (PRD 04 §9) already established, and `test_verify_assembly_thin_field_log_never_contains_clinical_text` already enforces, a house rule: this function logs a field's *path* and *length*, never its patient-facing content, explicitly commented "PHI/PHI-adjacent guard." A clinical number (a specific lab value, a specific dose) is exactly the kind of content that guard exists to keep out of application logs bound for Cloud Logging, even though this product handles no durable state or account. This PRD follows the same rule: the log line names the field path, the item index, and (for the unit-mismatch case) the *unit word* — a unit is generic vocabulary ("mg," "mL"), not patient data, so it's safe to log — but never the number itself and never the surrounding field text. This is strictly less debuggable than logging the actual value, and that trade is made deliberately for consistency with the established convention rather than re-litigated per-check (§9 records the alternative).

### 4.5 Failure behaviour and budgets

Trivial, unlike PRD 03/05's methods: `_check_numeric_parity` calls no LLM, takes no budget, and cannot raise — there is no failure mode beyond "logged a warning." It cannot make `_verify_assembly` itself fail, cannot affect `assemble_and_render`'s return value, and requires no fatal/non-fatal classification because it sits *inside* an already-classified fatal step (`assemble_and_render` is fatal per PRD 04 §4.5) purely as an additional log emission, never as a new failure path.

### 4.6 Behaviour on an item citing several facts

Backing is the **union** of number-tokens across every fact an item cites, not a per-fact requirement — matching how `MERGE` (`assemble_and_render.txt` line 30) already works: two facts stating "plaque in the left coronary artery" and "plaque in the right coronary artery" merge into one item, "heavy plaque in your left and right heart arteries." If each fact's `text` carries its own distinguishing detail with no shared number, this doesn't come up; but where a merge does carry a number (e.g., two facts each stating the same lab value from two draws), the item's rendered number only needs to appear in *at least one* of its citations, not all of them — the same soundness-not-completeness principle (01 §9, 03 §9) that governs `source_fact_ids` generally: a merged item is sound as long as something it cites backs each of its stated numbers, not as long as every cited fact's own numbers all separately reappear.

### 4.7 Shared-file seam with PRD 11 (omission-signal)

PRD 11 consumes `ReviewResult.coverage` — a different call (`review()`), a different concern (an omitted fact, not a corrupted number), and (per the batch's own scoping note) "also edits `pipeline.py`." This PRD's only edits to `pipeline.py` are: new module-level constants/functions placed adjacent to `_verify_assembly` and its existing helpers (§4.2-§4.4), and one new call (`_check_numeric_parity(result, facts)`) at the tail of `_verify_assembly`, before its `return`. Nothing in this PRD touches `review()`, `_sanitize_review_result`, or anything downstream of `assemble_and_render` — PRD 11's likely edit site is inside/around `review()`'s own sanitization or `iter_steps`, not `_verify_assembly`. The two PRDs should not produce a merge conflict at the function level; if PRD 11 also wants to add logging inside `_verify_assembly` for a different reason, note that this PRD's `_check_numeric_parity` call is the last statement before `_verify_assembly`'s `return` and should stay last, since it depends on the fully-`updates`-applied `result`, not the pre-guard `model`.

## 5. API Change Summary

**No schema, no API, no `output_data` change.** `_verify_assembly`'s signature is unchanged; nothing this PRD adds is serialized, persisted, or returned to the frontend. What changes is server-side log volume only:

| Behavior | Before this PRD | After |
|---|---|---|
| A rendered field's number matches none of its item's cited facts | Ships silently; only a non-fatal, unmeasured-catch-rate review LLM call stands between it and the patient | Ships identically (log-only, LOCKED) — but a `WARNING` log line records the field path and item index, and a per-run summary count is logged |
| A rendered field's number matches a cited fact's number but with a different/missing unit | Ships silently | Ships identically; logged as a distinct (softer) signal from "not found at all" |
| `assemble_and_render.txt`/`correct.txt`'s numeric guidance | One rule: never invent, never sharpen vague-to-exact | Adds: no added label, no added reference range, no rounding/truncation, no unit conversion, no percent/frequency reframe, no unattributed severity — reaches both prompts via the shared `_STYLE_RULES` constant |

## 6. Frontend Change Summary

None. No field, response shape, or rendering behavior visible to `CarePlanView.tsx` or any other frontend file changes as a result of this PRD.

## 7. Testing

### 7.1 `backend/tests/care_plan/test_pipeline_prompts.py` — additions (PRD 04 §7.2's style)

- `test_style_rules_contains_numeracy_block` — `"NUMERACY" in _STYLE_RULES`.
- `test_style_rules_numeracy_forbids_added_label` — asserts the "blood pressure 158/96" / "not... unless the fact says so" language is present.
- `test_style_rules_numeracy_forbids_reference_range` — asserts the "normal range" negative example is present.
- `test_style_rules_numeracy_forbids_rounding` — asserts the "ejection fraction 42%" example is present.
- `test_style_rules_numeracy_forbids_unit_conversion` — asserts the "creatinine 1.4 mg/dL" example is present.
- `test_style_rules_numeracy_forbids_percentage_frequency_reframe` — asserts the "3 out of 10 times" example is present.
- `test_style_rules_numeracy_permits_source_stated_interpretation` — asserts the "indicating poor control" permission example is present.
- `test_assemble_and_correct_prompts_both_receive_numeracy_block` — `.format()` both `_ASSEMBLE_PROMPT` and `_CORRECT_PROMPT` with their full required kwargs (reusing the existing `test_assemble_prompt_accepts_all_keys`/`test_correct_prompt_accepts_all_keys` fixtures) and assert `"NUMERACY"` appears in both formatted outputs — the regression guard that the shared-file decision (§4.1) actually reaches both call sites, mirroring `test_style_rules_is_non_empty_and_shared`'s existing pattern for `PII`.

### 7.2 New file: `backend/tests/care_plan/test_pipeline_numeric_parity.py`

**Tokenizer (`_extract_number_tokens`, `_normalize_number`, `_excluded_spans`):**
- `test_extract_number_tokens_normalizes_attached_vs_spaced_unit` — `"25mg"` and `"25 mg"` produce the identical token.
- `test_extract_number_tokens_is_case_insensitive_on_unit` — `"25MG"` and `"25mg"` match.
- `test_normalize_number_strips_leading_zeros` — `"025"` → `"25"`.
- `test_normalize_number_strips_trailing_decimal_zeros` — `"7.20"` and `"7.0"` normalize to `"7.2"` and `"7"` respectively.
- `test_extract_number_tokens_handles_thousands_separator` — `"1,000 units"` and `"1000 units"` match.
- `test_extract_number_tokens_matches_range` — `"5-10 days"` extracts one range token.
- `test_extract_number_tokens_keeps_slash_pair_with_trailing_unit` — `"158/96 mmHg"` (blood pressure) and `"1/2 tablet"` (fraction) are both kept as real tokens.
- `test_extract_number_tokens_excludes_bare_slash_pair_with_no_unit` — `"4/12"` alone yields no token.
- `test_extract_number_tokens_excludes_written_month_and_day` — `"April 12"` yields no token for `12`.
- `test_extract_number_tokens_excludes_time_of_day` — `"7:30 AM"` yields no token for either `7` or `30`.
- `test_extract_number_tokens_returns_empty_set_for_pure_word_frequency` — `"twice a day"` (the "BID" rewrite target) yields the empty set.

**Parity check (`_check_numeric_parity`, exercised through `_verify_assembly`, following `test_pipeline_assembly.py`'s established fixture conventions):**
- `test_numeric_parity_passes_silently_when_dosage_matches_cited_fact` — no warning logged.
- `test_numeric_parity_logs_when_dosage_drifts_from_cited_fact` — fact `text="metoprolol 25mg"`, item `dosage="250 mg"`; asserts a `WARNING` naming `medications[0].dosage`, and asserts the model returned by `_verify_assembly` is otherwise unchanged (log-only — no drop, no mutation of the field itself).
- `test_numeric_parity_logs_unit_mismatch_as_a_distinct_message_from_missing_value` — fact `text="warfarin 5 mg"`, item `dosage="5 mL"`; asserts the "different or missing unit" message, not the "not found in any cited fact" message.
- `test_numeric_parity_checks_union_of_multiple_cited_facts` — item cites two facts, each supplying half of a merged rendering's numbers; no false positive.
- `test_numeric_parity_ignores_field_with_no_digits` — a `why` field with ordinary prose and a fact with a number in a different field; no warning tied to the digit-free field.
- `test_numeric_parity_flags_added_reference_range_not_in_any_cited_fact` — fact `text="A1c 7.2%"`, item `description="A1c 7.2% (normal range 4.0-5.6%)"`; the injected range's numbers are flagged even though `7.2` itself matches — the parity check's incidental defense-in-depth catch of an R2-forbidden interpretive addition, purely because those numbers are genuinely absent from the fact.
- `test_numeric_parity_does_not_flag_bid_to_twice_daily_rewrite` — fact `text="metoprolol BID"` (however grounding renders that; use `"metoprolol twice daily"` if grounding already expands it, per `ground.txt` line 11), item `frequency="twice a day"`; no digits on either side, no warning.
- `test_numeric_parity_does_not_flag_date_reformatted_to_month_name` — fact `text="follow-up 4/12"`, item `time_frame="Follow up on April 12."`; no warning (the disclosed blind spot, asserted as intended behavior, not an accident).
- `test_numeric_parity_summary_checked_against_summary_fact_ids` — a drifted number in `summary` against `summary_fact_ids`' facts is flagged the same way an item field is.
- `test_numeric_parity_skips_diagnosis_and_reason_for_visit` — a numeric mismatch planted in `diagnosis.details[0].description` (which has no `source_fact_ids` to check against) produces no warning and no error — documents the structural non-coverage rather than silently relying on it.
- `test_numeric_parity_log_never_contains_the_raw_digits_or_field_text` — the PHI-adjacent guard, mirroring `test_verify_assembly_thin_field_log_never_contains_clinical_text` directly: plant a distinctive dosage value, assert it (and its `repr()`) never appears in any `caplog` record, while the field path does.
- `test_numeric_parity_never_mutates_or_drops_the_care_plan` — parametrized across a mismatch and a match; `_verify_assembly`'s returned model is field-for-field identical to what assembly produced (aside from the pre-existing three guards), regardless of what the parity check logged.

## 8. Manual Intervention Required From You

- **Prompt smoke test against real notes**, once this lands (ngrok + pm2, `SERVICE_MODE=combined` — no separate wiring step needed, unlike PRD 05's `review`/`correct`, since `_verify_assembly` is already live in `iter_steps`): confirm the `NUMERACY` block doesn't make the model *more* conservative in an unintended way (e.g., refusing to render a value at all rather than copying it verbatim) and spot-check the parity check's log volume on 5-10 real/realistic notes for false positives from the disclosed blind spots (§4.2, §9) — particularly standalone ordinal dates and any note with an unusual number format not anticipated here.
- **Decide whether the false-positive rate is low enough to eventually promote a numeric-parity failure into a pre-seeded reviewer correction** (feeding it into `review()`/`correct()`'s corrections list rather than only logging it) — explicitly out of scope for this PRD per the batch's locked log-only instruction, but the natural next step the source comparison doc names once real log data exists (§9).
- **Tune `_UNIT_WORD_MAX_LENGTH` (15)** if real notes surface a legitimate compound unit longer than 15 characters that gets truncated, or a false unit-match shorter than that gets over-captured.
- No new environment variables, credentials, or console configuration — this sub-project is prompt + pure Python only.

## 9. Open Questions & Decisions

- `[RESOLVED: the NUMERACY block is added to the shared _style_rules.txt, reaching both assemble_and_render.txt and correct.txt, not confined to a separate assemble-only block.]` — the corrector re-renders fact-sourced values under the same "restyle in the document's voice" instruction assembly does (PRD 05 §4.4); omitting it from `correct.txt` would leave the corrector free to introduce exactly the interpretive additions this PRD exists to forbid, and duplicating the text was already rejected once (PRD 05 §4.4) for the identical drift-risk reason.
- `[RESOLVED: the numeric-parity check compares rendered fields against Fact.text, not quote_for()/Unit.text, and does not thread `units` into assemble_and_render or _verify_assembly.]` — `Fact.text` is the only view of a fact assembly's own prompt ever shows the model (`_format_facts_for_prompt`), so it is the correctly-scoped anchor for "did rendering preserve what assembly was given"; `quote_for()` is explicitly permitted by `ground.txt` to be a shorter excerpt than the full clause, which would manufacture false positives on legitimately-rendered detail outside the short quote; falling back to the full `Unit.text` to fix that trades it for a same-line cross-contamination false negative instead. See §4.3.
- `[DEFERRED: a second check layer comparing against quote_for()/Unit.text (with units threaded through), to also catch a numeric error introduced by grounding's own paraphrase step rather than assembly's rendering step.]` — real, but no evidence yet that grounding-introduced numeric drift (distinct from the assembly-introduced drift this PRD targets) is an observed problem; would require resolving the short-quote-coverage gap named in §4.3 before it could avoid manufacturing its own false positives. Revisit if PRD 03's `_is_verbatim_quote` is ever extended to check `text`-vs-`quote` numeric consistency at grounding time, which would be the more natural home for that concern than bolting it onto assembly's check.
- `[RESOLVED: date- and time-shaped spans are excluded from numeric-parity comparison entirely, on both sides, rather than resolved to a canonical value for comparison.]` — a genuinely corrupted date/time is a disclosed, accepted blind spot; the rejected alternative (month-name mapping, AM/PM arithmetic, DD/MM-vs-MM/DD disambiguation) is disproportionate engineering for a log-only signal and risks manufacturing false positives from a wrong disambiguation guess, worse than the gap it would close. See §4.2.
- `[RESOLVED: a standalone ordinal day-of-month with no adjacent month name ("on the 12th") is accepted as-is; no defensive exclusion is built.]` No evidence this occurs in the app's actual note distribution, and this project does not build defensively against unobserved cases. The §8 manual smoke test is the trigger to revisit, if it ever shows up there.
- `[RESOLVED: numbered steps[] prefixes are not defended against.]` `assemble_and_render.txt` contains no numbering instruction today (verified by inspection), so there is nothing to defend against. If that prompt is ever changed to instruct numbered `steps[]` prefixes, whoever makes that change owns updating this check accordingly.
- `[DEFERRED: Fact.text's own numeric fidelity to the source note is unchecked by any existing deterministic gate.]` `_verify_ledger`'s three checks (unit exists, quote verbatim, quote informative) verify `quote`, never that `text`'s numbers match `quote`'s numbers or the source. This is a known, bounded gap that belongs to PRD 03's `_verify_ledger`, not to assembly; this PRD's check inherits `Fact.text` as ground truth by design and stops there.
- `[RESOLVED: logging names field path, item index, and (for a unit mismatch) the unit word, but never the number itself or the surrounding field text.]` — matches this file's existing PHI-adjacent convention, established by `_log_thin_fields` and enforced by `test_verify_assembly_thin_field_log_never_contains_clinical_text`. Alternative considered: log the actual mismatched value, which would be strictly more useful for debugging and matches the sibling comparison doc's own R1 recommendation ("log the `present=False` fact ids with their text and category") for the *coverage* signal in PRD 11 — rejected here for consistency with the convention already established in this exact file; flagged as a cross-PRD inconsistency worth resolving centrally (a single house policy on "how much clinical content may a log line carry") if PRD 11 adopts the opposite convention for its own new log lines.
- `[RESOLVED: a same-number-different-unit case is logged as a distinct, softer signal from "number not found at all."]` — cheap once the token set already exists (no extra pass), and a unit swap is exactly the failure mode the NUMERACY block's "never convert a unit" rule targets, so this gives that specific rule its own independent, deterministic detector for free.
- `[RESOLVED: parity is checked against the union of number-tokens across all of an item's cited facts, not required per-fact.]` — matches how MERGE already combines multiple facts into one item (§4.6); requiring a number to reappear in every cited fact would be a completeness-shaped check, which the soundness-over-completeness inversion (01 §9, 03 §9) already retired as this project's governing contract.
- `[RESOLVED: diagnosis.details and reason_for_visit are outside this check's reach.]` — neither carries `source_fact_ids` (PRD 01's decided scope: only the six item models do); this is a pre-existing structural gap this PRD did not introduce and, per its own non-goals, does not retrofit.
- `[RESOLVED: this PRD requires no change to assemble_and_render's or iter_steps's signature and activates immediately on landing.]` — a direct consequence of anchoring on `Fact.text` (§4.3); unlike PRD 05's `review`/`correct`, there is no PRD-06-style separate wiring step for this check to wait on.
