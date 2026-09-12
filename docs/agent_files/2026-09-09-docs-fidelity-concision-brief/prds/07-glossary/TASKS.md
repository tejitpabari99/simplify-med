# Tasks: Glossary

PRD: [`PRD.md`](./PRD.md) (this folder). Depends on: 01 (schema-and-config) — `CarePlan`/item-model shape is unaffected by this PRD but `render_care_plan_text` (Task 9) reads the settled field names, including 01's `status`/`source_fact_ids`/`summary_fact_ids` additions; 04 (assemble-and-render) — `assemble_and_render` always returns `terms == {}` and is what this PRD's `build_glossary_from_care_plan` re-detects against once 06 wires the two together. Neither 01's nor 04's code exists in this repo yet at PRD-authoring time; their tasks are tracked in `prds/01-schema-and-config/TASKS.md` and `prds/04-assemble-and-render/TASKS.md` and are **not** duplicated here. Depended on by: 06 (pipeline-orchestration — wires the background-thread submission of `curate_glossary_terms` and consumes `render_care_plan_text` for the "after" readability score), 08 (frontend — reads the *set* of keys this sub-project produces, no code change needed).

**Conventions**

- Backend tests: from `backend/`, run `python -m pytest tests/ -q` (matches CI). To run a single file/test: `python -m pytest tests/utils/test_jargon_db.py -q` or `...::test_name -q`. `pyproject.toml`'s `addopts` already adds `--cov=. --cov-report=term-missing`; no extra flags needed.
- Lint (optional but matches repo config): `ruff check .` from `backend/`.
- No frontend changes in this PRD (§3 Non-Goals, §6) — no frontend test commands needed here.
- Do every task in this file on branch `docs/fidelity-concision-brief`, one task per commit, in the order given (later tasks depend on earlier ones landing first — see each task's dependency note).
- Every task traces to PRD `## 4. Architecture Decisions`; do not add fields, files, or behavior beyond what's cited.
- **Verified against the real, currently-checked-in code** (not a future state): `backend/utils/jargon_db.py`, `backend/utils/term_detection.py`, `backend/utils/text_normalization.py`, `backend/data/jargon/sources.json`, `backend/data/jargon/michigan_medical_dictionary.json` (1,962 records; all 14 starter-stoplist words confirmed present as bare canonical `term` values, including `"foot, feet"`), `backend/scripts/cleanup_anonymous_users.py` (the one-off-script precedent), `backend/models/care_plan/care_plan.py`, `backend/utils/constants.py` (`Constants.Llm.MAX_TOKENS = 8192`, `MAX_TOKENS_LONG_FORM = 65536`, `TEMPERATURE_JSON = 0.2`), `backend/utils/llm.py` (`LLMClient.generate_json(prompt, temperature=..., max_tokens=...) -> dict | list`).

---

### Task 1 — Fix `build_terms_glossary` keying bug; rename `_get_source_name` → `get_source_name`

   - Files: `backend/utils/jargon_db.py`
   - Changes (PRD §4.1):
     - Replace `build_terms_glossary` (currently `jargon_db.py:279-294`, keyed on `hit["term"]`) with:
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
     - Rename `_get_source_name` (currently `jargon_db.py:50-56`) to public `get_source_name` — no other change to its body. Update its two in-module call sites (`_plain_language_rows`, `_medical_rows`, `_abbreviation_rows` — three call sites in the current file, all named `_get_source_name(...)`) to call `get_source_name(...)`.
   - Dependency: none (first task; touches only this file).
   - Acceptance criteria:
     - `grep -n "_get_source_name" backend/utils/jargon_db.py` returns zero hits; `grep -n "def get_source_name" backend/utils/jargon_db.py` returns exactly one hit.
     - `build_terms_glossary([{"term": "plaque (in an artery)", "matched_term": "plaque", "definition": "d", "source": "s", "imgUrl": None, "altText": None}])` returns `{"plaque": {"definition": "d", "source": "s", "imgUrl": None, "altText": None}}` — the key is `"plaque"`, not `"plaque (in an artery)"`.
     - `build_terms_glossary([{"term": "x", "definition": "d", "source": "s"}])` (no `matched_term` key) raises `KeyError` — proves the strict-access contract from PRD §9's resolved decision, not a silent `.get(...)` fallback.
     - `from utils.jargon_db import get_source_name; get_source_name("michigan_medical_dictionary")` (from `backend/`) resolves the same string `_medical_rows()` already resolves internally today.
     - Every existing caller of `build_terms_glossary` (`lookup_medical_terms` via `preserve_and_define_terms` is not itself a caller — confirm via `grep -rn "build_terms_glossary" backend --include=*.py`, currently only `term_detection.py`'s `build_glossary_from_simplified_text`) still compiles; its own tests are fixed in Task 2.

### Task 2 — Fix and extend `backend/tests/utils/test_jargon_db.py`

   - Files: `backend/tests/utils/test_jargon_db.py`
   - Dependency: land after Task 1.
   - Changes (PRD §7.1):
     - In `TestBuildTermsGlossary.test_builds_dict_from_hits` and `test_last_write_wins_for_duplicates`, add `"matched_term"` (equal to `"term"` in both fixtures, since neither test exercises alias-divergence) to every hit dict, e.g.:
       ```python
       def test_builds_dict_from_hits(self):
           hits = [
               {"term": "Hypertension", "matched_term": "Hypertension", "definition": "High blood pressure", "source": "test", "imgUrl": None, "altText": None},
           ]
           glossary = build_terms_glossary(hits)
           self.assertIn("Hypertension", glossary)
           self.assertEqual(glossary["Hypertension"]["definition"], "High blood pressure")
       ```
       (and the analogous change for `test_last_write_wins_for_duplicates`, adding `"matched_term": "Stroke"` to both hit dicts).
     - Add four new tests to `TestBuildTermsGlossary` (load-bearing regressions, named exactly as the PRD's task requirement):
       ```python
       def test_build_terms_glossary_keys_on_matched_term_not_term(self):
           hits = [{
               "term": "plaque (in an artery)", "matched_term": "plaque",
               "definition": "d", "source": "s", "imgUrl": None, "altText": None,
           }]
           glossary = build_terms_glossary(hits)
           self.assertIn("plaque", glossary)
           self.assertNotIn("plaque (in an artery)", glossary)

       def test_lookup_medical_terms_plaque_in_artery_matches_bare_alias(self):
           normalized = normalize_text("heavy plaque was seen")
           hits = lookup_medical_terms(normalized)
           plaque_hits = [h for h in hits if h["matched_term"] == "plaque"]
           self.assertTrue(plaque_hits, f"Expected a 'plaque' hit, got: {hits}")

       def test_build_terms_glossary_abdomen_abdominal_keys_on_matched_alias(self):
           hits = [{
               "term": "abdomen, abdominal", "matched_term": "abdominal",
               "definition": "d", "source": "s", "imgUrl": None, "altText": None,
           }]
           glossary = build_terms_glossary(hits)
           self.assertIn("abdominal", glossary)
           self.assertNotIn("abdomen, abdominal", glossary)

       def test_get_source_name_is_public(self):
           from utils.jargon_db import get_source_name
           self.assertEqual(
               get_source_name("michigan_medical_dictionary"),
               "University of Michigan Plain Language Medical Dictionary",
           )
       ```
       (`test_lookup_medical_terms_plaque_in_artery_matches_bare_alias` runs end-to-end against the real, currently-checked-in dictionary — verified at authoring time that `michigan_medical_dictionary.json` has both `"plaque (in an artery)"` and `"plaque (on teeth)"` as canonical terms and `lookup_medical_terms`'s `seen`/`seen_terms` sets guarantee only one wins per call, so this assertion holds regardless of which one does.)
   - Acceptance criteria: `python -m pytest tests/utils/test_jargon_db.py -q` (from `backend/`) passes in full, including all four new tests and the two updated fixtures.

### Task 3 — New data file `common_word_stoplist.json`; new script `backend/scripts/prune_jargon_stoplist.py`

   - Files: `backend/data/jargon/common_word_stoplist.json` (new), `backend/scripts/prune_jargon_stoplist.py` (new)
   - Dependency: none (independent of Tasks 1-2; a separate data/script pair).
   - Changes (PRD §4.2):
     - Create `backend/data/jargon/common_word_stoplist.json` with exactly the 14-word verified starter list:
       ```json
       ["heart", "blood", "pain", "brain", "stomach", "fever", "ability",
        "fatigue", "control", "medicine", "treatment", "symptom", "risk",
        "foot, feet"]
       ```
     - Create `backend/scripts/prune_jargon_stoplist.py` with exactly this contract (matches the `backend/scripts/cleanup_anonymous_users.py` precedent — a one-off, checked-in, re-runnable maintenance script, not part of the request-serving app; this one has no Cloud Run Job wrapper since it's a local, manually-invoked data-curation tool, not a scheduled job):
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
   - Acceptance criteria:
     - `python -c "from scripts.prune_jargon_stoplist import prune, _branches"` (from `backend/`) succeeds.
     - `json.loads(open("backend/data/jargon/common_word_stoplist.json").read())` is a flat list of 14 lowercase strings, including `"foot, feet"`.
     - Do **not** run the script yet in this task — Task 5 runs it against the real dictionary as its own reviewable step. This task only creates the files.

### Task 4 — New `backend/tests/scripts/test_prune_jargon_stoplist.py` (synthetic cases)

   - Files: `backend/tests/scripts/test_prune_jargon_stoplist.py` (new file)
   - Dependency: land after Task 3.
   - Changes (PRD §7.2, first three cases — synthetic, not against the real dictionary):
     ```python
     """Tests for scripts/prune_jargon_stoplist.py — deterministic dictionary prune."""
     from scripts.prune_jargon_stoplist import prune


     def test_prune_drops_records_whose_every_branch_is_stoplisted():
         dictionary = [
             {"term": "heart", "definition": "d1"},
             {"term": "plaque (in an artery)", "definition": "d2"},
             {"term": "abdomen, abdominal", "definition": "d3"},
         ]
         kept, dropped = prune(dictionary, {"heart"})
         assert [r["term"] for r in dropped] == ["heart"]
         assert {r["term"] for r in kept} == {"plaque (in an artery)", "abdomen, abdominal"}


     def test_prune_never_drops_a_parenthetical_term():
         dictionary = [{"term": "plaque (in an artery)", "definition": "d"}]
         # Stoplist deliberately includes the bare, paren-stripped form.
         kept, dropped = prune(dictionary, {"plaque"})
         assert dropped == []
         assert kept == dictionary


     def test_prune_keeps_record_if_any_branch_survives():
         dictionary = [{"term": "abdomen, abdominal", "definition": "d"}]
         kept, dropped = prune(dictionary, {"abdomen"})
         assert dropped == []
         assert kept == dictionary
     ```
   - Acceptance criteria: `python -m pytest tests/scripts/test_prune_jargon_stoplist.py -q` (from `backend/`) passes with all three tests present.

### Task 5 — Run the prune against the real dictionary; commit the pruned file; add the fourth regression test

   - Files: `backend/data/jargon/michigan_medical_dictionary.json` (rewritten in place), `backend/tests/scripts/test_prune_jargon_stoplist.py` (append one test)
   - Dependency: land after Task 3 (script and stoplist must exist) and Task 4 (keep the synthetic tests passing before touching the real file).
   - Changes (PRD §4.2, §7.2 row 4, §8):
     - Run `python scripts/prune_jargon_stoplist.py` from `backend/`. At authoring time, all 14 stoplist words (`heart`, `blood`, `pain`, `brain`, `stomach`, `fever`, `ability`, `fatigue`, `control`, `medicine`, `treatment`, `symptom`, `risk`, `foot, feet`) are confirmed present as bare canonical `term` values in the 1,962-record dictionary and none of them appears with a parenthetical qualifier, so the script is expected to print 14 dropped records and rewrite the file with 1,948 records remaining. Commit the rewritten `michigan_medical_dictionary.json` as-is.
     - Append the fourth regression test to `backend/tests/scripts/test_prune_jargon_stoplist.py`:
       ```python
       import json
       from pathlib import Path

       _DICTIONARY_PATH = Path(__file__).resolve().parents[2] / "data" / "jargon" / "michigan_medical_dictionary.json"


       def test_committed_dictionary_excludes_named_stoplist_examples():
           dictionary = json.loads(_DICTIONARY_PATH.read_text())
           bare_terms = {record["term"] for record in dictionary}
           for word in ("heart", "blood", "pain", "brain", "stomach", "fever", "ability"):
               assert word not in bare_terms, f"{word!r} should have been pruned"
       ```
   - Acceptance criteria:
     - `python -m pytest tests/scripts/test_prune_jargon_stoplist.py -q` (from `backend/`) passes in full, including the new test against the real committed file.
     - `python -m pytest tests/utils/test_jargon_db.py tests/utils/test_term_detection.py -q` (from `backend/`) still passes — the prune only removes rows tests don't depend on (`abatement`, `absence`, `plaque`, `bid` are all untouched by the 14-word stoplist).
     - **Flagged for your review, not blocking this task's completion (PRD §8):** read the script's printed drop list (each dropped `term` + first 70 characters of its `definition`) before treating this diff as final, and pay particular attention to `"foot, feet"` — flagged by the PRD itself as borderline (very basic anatomy, but arguably more concrete/useful to a patient than `"ability"` or `"control"`). If your review finds it should not have been dropped, or finds other everyday words the 14-word starter list missed, extend `common_word_stoplist.json` and re-run the script — this is the data-curation follow-up the PRD explicitly defers (§9 `[DEFERRED]`), not a defect in this task.

### Task 6 — Add the `llm_proposed` source entry to `sources.json`

   - Files: `backend/data/jargon/sources.json`
   - Dependency: none (independent of Tasks 1-5; needed before Task 8, which resolves this id via `get_source_name("llm_proposed")`).
   - Changes (PRD §4.5): append a fourth entry to the existing three-entry JSON array:
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
   - Acceptance criteria:
     - `json.loads(open("backend/data/jargon/sources.json").read())` has exactly 4 entries; the fourth has `"id": "llm_proposed"`.
     - `from utils.jargon_db import get_source_name; get_source_name("llm_proposed")` (from `backend/`, after Task 1's rename) returns `"Proposed by the glossary curation model (not from a fixed dictionary)"`.
     - The three existing entries (`ahrq_plain_language`, `michigan_medical_dictionary`, `local_abbreviations`) are byte-for-byte unchanged.

### Task 7 — New prompt file `backend/care_plan/prompts/curate_glossary.txt`

   - Files: `backend/care_plan/prompts/curate_glossary.txt` (new file)
   - Dependency: none (independent data file; needed before Task 8 loads it).
   - Changes (PRD §4.3): create the file with exactly this text (copy verbatim — Task 10's regression tests assert exact substrings):
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
   - Acceptance criteria:
     - The file exists, is non-empty, and contains the literal placeholders `{max_terms}` (twice), `{detected_terms_block}`, `{source_text}` exactly.
     - `grep -c "plaque" backend/care_plan/prompts/curate_glossary.txt` returns at least 1 (the worked example).
     - `grep -c "calcified\|contrast\|circumflex" backend/care_plan/prompts/curate_glossary.txt` returns at least 1 for each.
     - Covered permanently by Task 10's prompt-loading tests.

### Task 8 — `curate_glossary_terms` in `backend/utils/term_detection.py`

   - Files: `backend/utils/term_detection.py`
   - Dependency: land after Task 1 (`get_source_name` must be public), Task 6 (`llm_proposed` source id must resolve), and Task 7 (prompt file must exist).
   - Changes (PRD §4.3):
     - Add imports at the top of the file (alongside the existing ones): `from pathlib import Path`, `from utils.jargon_db import (... existing four names ..., get_source_name)`, `from utils.llm import LLMClient`, `from utils.constants import Constants`.
     - Add the prompt-loading constant, mirroring `care_plan/pipeline.py`'s `_PROMPTS_DIR` pattern but resolved relative to `utils/` (this file's own directory), not `care_plan/`:
       ```python
       _PROMPTS_DIR = Path(__file__).resolve().parent.parent / "care_plan" / "prompts"
       _CURATE_PROMPT = (_PROMPTS_DIR / "curate_glossary.txt").read_text(encoding="utf-8")
       _CURATION_PROPOSAL_HINT = 15   # model-facing hint, not enforced
       _CURATION_TOTAL_BACKSTOP = 40  # code-enforced, covers kept + proposed_hits
       ```
     - Add a formatting helper for the prompt's DETECTED TERMS section, matching this file's existing `format_medical_terms_for_prompt`/`format_abbreviations_for_prompt` style but including each term's definition (the curation prompt needs it; the assembly prompt's existing formatter does not):
       ```python
       def _format_detected_terms_for_curation(detected_terms: list[dict]) -> str:
           """Format Michigan-dictionary hits as 'term: definition' lines for the
           curation prompt's DETECTED TERMS section (PRD 07 SS4.3)."""
           if not detected_terms:
               return "(none detected)"
           return "\n".join(f"- {t['term']}: {t['definition']}" for t in detected_terms)
       ```
     - Add `curate_glossary_terms`, exactly as specified (full docstring reproduced verbatim — it documents the fail-open contract 06 relies on):
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
       `contains_normalized_term` and `normalize_text` are already imported at the top of this file — no new import needed for them.
   - Failure classification (PRD §4.3): non-fatal, self-contained — the function catches its own exceptions and never raises; there is no `iter_steps` fatal/non-fatal wrapping decision for 06 to make here. Budgets: `temperature=Constants.Llm.TEMPERATURE_JSON` (0.2), `max_tokens=Constants.Llm.MAX_TOKENS` (8,192 — the default, not `MAX_TOKENS_LONG_FORM`, since this call emits a short drop-list plus a handful of short definitions).
   - Acceptance criteria:
     - `python -c "from utils.term_detection import curate_glossary_terms"` (from `backend/`) succeeds.
     - `curate_glossary_terms` calls `LLMClient.generate_json` with `max_tokens=Constants.Llm.MAX_TOKENS` and `temperature=Constants.Llm.TEMPERATURE_JSON` (not the long-form budget).
     - Every existing test in `backend/tests/utils/` still passes unchanged (`python -m pytest tests/utils/ -q` from `backend/`) — this task is purely additive to the module.
     - Permanent behavioral tests land in Task 10.

### Task 9 — `render_care_plan_text`, `build_glossary_from_care_plan`; delete `build_glossary_from_simplified_text`

   - Files: `backend/utils/term_detection.py`
   - Dependency: land after Task 1 (`build_terms_glossary`'s new contract) and Task 8 (same file; land as a separate commit immediately after).
   - Changes (PRD §4.4):
     - Add `from typing import TYPE_CHECKING` to the imports and, mirroring the existing forward-reference pattern in `backend/models/pipeline_events.py`:
       ```python
       if TYPE_CHECKING:
           from models.care_plan.care_plan import CarePlan
       ```
     - Add `render_care_plan_text`, exactly as specified (full docstring reproduced verbatim — it documents both consumers and the exclusion list):
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
     - Delete `build_glossary_from_simplified_text` (currently `term_detection.py:77-107`) and replace it with `build_glossary_from_care_plan`:
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
       This is logic-identical to the deleted function — only the input type changes (`CarePlan` instead of a prose `str`), by routing through `render_care_plan_text` first. `inflected_aliases`, `normalize_text`, `contains_normalized_term`, `build_terms_glossary` are already imported at the top of this file.
   - **Known, accepted consequence — larger in scope than any single-file gap elsewhere in this decomposition, disclosed here in full because no test-running step should discover it by surprise:** `backend/care_plan/pipeline.py` (06's file, not touched by this PRD per §3 Non-Goals — "does not touch `care_plan/pipeline.py::iter_steps`") has a module-level import `from utils.term_detection import (build_glossary_from_simplified_text, ...)` and calls it by that name inside `iter_steps` (currently `pipeline.py:35`, `:236`). Once this task lands, `care_plan/pipeline.py` raises `ImportError` merely by being imported — not just on a real invocation, the way PRD 04's analogous method-deletion gap works (04's gap only fires at call time, and 04's own Task 2 verified no test triggers it). This one fires at **module load**, and cascades through the real, verified-at-authoring-time import chain: `care_plan/pipeline.py` → `services/care_plan_pipeline.py` → `routes/worker.py` → `routes/__init__.py` → `app.py`. Concretely, until 06 rewires `iter_steps` to call `build_glossary_from_care_plan` instead (06's job — PRD §9's `[RESOLVED]` hand-off, confirmed against both 06 and 07's PRDs), `python -m pytest tests/ -q` will show **collection errors** (not ordinary test failures) in every test file that imports any of the above at module scope — verified at authoring time to include at least `tests/care_plan/test_pipeline_streaming.py`, `tests/care_plan/test_pipeline_executors.py`, `tests/care_plan/test_pipeline_prompts.py`, `tests/care_plan/test_pipeline_schema.py`, `tests/care_plan/test_pipeline_assembly.py` (04's new file), and every test that imports `app` or `routes.worker` (e.g. `tests/routes/test_worker.py`, `tests/routes/test_jobs_e2e_scenarios.py`, `tests/routes/test_health_route.py`, `tests/integration/test_container_startup.py`, `tests/models/test_envelope.py`, `tests/utils/test_app_observability.py`, `tests/utils/test_care_plan_markers.py`). This is exactly the deletion PRD §4.6's module-wiring table calls for ("**deleted**, replaced by `build_glossary_from_care_plan`") and is not a defect in this task — fixing the `pipeline.py` import/call site is explicitly out of this PRD's scope (§3 Non-Goals) and explicitly 06's job (§9). Do not work around it by leaving `build_glossary_from_simplified_text` in place, and do not edit `care_plan/pipeline.py` to patch the import — both would be scope this PRD's own text forbids. Task 11 below carves this out precisely rather than silently expecting a green full suite.
   - Acceptance criteria:
     - `grep -n "build_glossary_from_simplified_text" backend/utils/term_detection.py` returns zero hits; `grep -n "def build_glossary_from_care_plan\|def render_care_plan_text" backend/utils/term_detection.py` each return exactly one hit.
     - Calling `render_care_plan_text` twice on the same `CarePlan` input returns identical output (pure function, no side effects).
     - `render_care_plan_text` joins non-empty field values with `"\n\n"`.
     - `build_glossary_from_care_plan` finds a term whose only occurrence is in `diagnosis.details[0].description` (proves the full projection feeds re-detection, not just `summary`).
     - Permanent tests land in Task 10.

### Task 10 — Extend `backend/tests/utils/test_term_detection.py`

   - Files: `backend/tests/utils/test_term_detection.py`
   - Dependency: land after Task 8 and Task 9.
   - Changes (PRD §7.3): add the following tests. This file currently uses `unittest.TestCase`-free module-level `unittest.TestCase` classes for `detect_terms`; add new tests either as additional `unittest.TestCase` classes (matching the file's existing convention) or plain `pytest`-style functions — either is acceptable since this file has no existing convention against it, but keep all new tests in this one file per PRD §7.3's file scope. Construct a minimal `CarePlan` via `models.care_plan.care_plan.CarePlan(doc_type="care_plan", version=Constants.Schema.CARE_PLAN_VERSION, summary=...)` plus whichever nested item models each test needs (import `CarePlan`, `Medication`, `DiagnosisDetail`, `Diagnosis` etc. from `models.care_plan.care_plan`; import `Constants` from `utils.constants`).
     - `test_render_care_plan_text_includes_summary_and_medication_fields` — build a `CarePlan` with `summary="You came in for a checkup."` and one `Medication(why="Because your blood pressure is high.")`; assert both strings appear in `render_care_plan_text(care_plan)`, `summary` before the medication's `why`.
     - `test_render_care_plan_text_excludes_internal_fields` — build a `CarePlan` with `note="internal note text"` and `summary_fact_ids=[1, 2, 3]` set; assert neither `"internal note text"` nor any stringified id representation leaks into the projection.
     - `test_render_care_plan_text_is_deterministic` — call `render_care_plan_text(care_plan)` twice on the same instance; assert the two results are equal.
     - `test_render_care_plan_text_joins_fields_as_separate_paragraphs` — a `CarePlan` with exactly `summary="First."` and one `ReasonForVisit(reason="Second.")`; assert `"First.\n\nSecond."` appears in the result (guards `utils/scoring.py`'s paragraph regex against a future `" "`-join regression).
     - `test_build_glossary_from_care_plan_finds_term_in_diagnosis_but_not_medications` — a `CarePlan` whose only occurrence of a jargon term (e.g. `"plaque"`) is in `diagnosis.details[0].description`, with `medications` empty or unrelated; a `detected_terms` list containing a hit for `"plaque"` (`{"term": "plaque", "matched_term": "plaque", "definition": "d", "source": "s", "imgUrl": None, "altText": None}`); assert `build_glossary_from_care_plan(care_plan, detected_terms)` contains `"plaque"`.
     - `test_curate_glossary_terms_falls_back_on_llm_failure` — a stub `llm_client` whose `generate_json` raises; assert `curate_glossary_terms("some text", detected_terms, llm_client=stub)` returns `detected_terms` unchanged and no exception propagates.
     - `test_curate_glossary_terms_drops_named_common_word` — stub `generate_json` returns `{"drop": ["heart"], "propose": []}`; `detected_terms` has one hit with `term="heart"` and one with `term="plaque"`; assert the result contains the `plaque` hit and not the `heart` hit.
     - `test_curate_glossary_terms_proposes_new_term_found_in_source` — stub `generate_json` returns `{"drop": [], "propose": [{"matched_term": "circumflex", "definition": "d"}]}`; `source_text` contains `"circumflex"`; assert the result contains a hit with `matched_term == "circumflex"` and `source == get_source_name("llm_proposed")`.
     - `test_curate_glossary_terms_rejects_proposed_term_not_in_source` — same stub as above, but `source_text` does not contain `"circumflex"`; assert no hit with `matched_term == "circumflex"` is present in the result (§4.3's substring guard).
     - `test_curate_glossary_terms_backstop_truncates_proposed_before_kept` — `detected_terms` has 35 entries (none dropped by the stub), stub `propose` returns 10 new terms all found in `source_text`; assert the result has exactly 40 entries and all 35 original `detected_terms` entries are among them (proves truncation cuts `proposed_hits` first).
   - Acceptance criteria: `python -m pytest tests/utils/test_term_detection.py -q` (from `backend/`) passes in full, including all ten cases above plus every pre-existing `detect_terms` test (unaffected by this PRD).

### Task 11 — Full-suite verification

   - Files: none (verification only)
   - Changes: none.
   - Dependency: land after Tasks 1-10.
   - Acceptance criteria:
     - From `backend/`, `python -m pytest tests/utils/test_jargon_db.py tests/utils/test_term_detection.py tests/scripts/test_prune_jargon_stoplist.py -q` passes with zero failures — this is the portion of the suite entirely within this PRD's own file scope.
     - From `backend/`, `python -m pytest tests/ -q` is expected to show **collection errors** (not assertion failures) in exactly the files listed in Task 9's "Known, accepted consequence" note — confirm the failures are *only* import-chain collection errors naming `build_glossary_from_simplified_text`/`ImportError`/`ModuleNotFoundError` against `care_plan.pipeline`, `services.care_plan_pipeline`, `routes.worker`, or `app`, and that no other, unrelated test in the suite fails. List the exact set of failing files against the note's predicted list — if the actual set differs (larger or smaller), record which files differ and why, so whoever wires 06 has an accurate, current picture rather than a stale prediction.
     - `grep -rn "build_glossary_from_simplified_text\|_get_source_name" backend --include=*.py` returns hits **only** inside `backend/care_plan/pipeline.py` (the accepted, disclosed gap above) — zero hits anywhere else, confirming this PRD's own files are fully migrated.
     - `ruff check .` (from `backend/`) is clean for every file this PRD touched (`utils/jargon_db.py`, `utils/term_detection.py`, `scripts/prune_jargon_stoplist.py`, and the four touched/new test files).

---

## Handed off to other sub-projects (specified here, not implemented here — do not action as part of this task list)

Per PRD §3 Non-Goals and its header cross-references, the following are **out of scope for this PRD's tasks** even though this PRD's own text specifies exactly what they must do:

- **To 06 (pipeline-orchestration)**: wiring `curate_glossary_terms` into a background `ThreadPoolExecutor.submit(...)` call inside `care_plan/pipeline.py::iter_steps`, immediately after `detect_terms` completes — the exact call site is 06's decision since `term_data` is only visible inside `iter_steps`, not at the `services/care_plan_pipeline.py` adapter layer where the `before_score` precedent lives (PRD §9 `[RESOLVED]`). No `iter_steps` fatal/non-fatal wrapping decision is needed for this call — `curate_glossary_terms` never raises.
- **To 06**: rewiring `iter_steps` to call `build_glossary_from_care_plan(care_plan, curated_terms)` in place of the deleted `build_glossary_from_simplified_text(clarified, ...)` — this is exactly the interface-gap closure Task 9's "Known, accepted consequence" note describes; 06 owns the edit to `care_plan/pipeline.py` that resolves it.
- **To 06**: replacing `score_text_safe(event.clarified, "after")` (`services/care_plan_pipeline.py:106`) with `score_text_safe(render_care_plan_text(event.care_plan), "after")` once `PipelineRunResult.clarified` no longer exists (PRD §4.4).
- **To 06**: renumbering `Constants.Pipeline.PIPELINE_STEPS` / any step-count or progress-event changes related to when `curate_glossary_terms` runs relative to other steps.
- **To 08 (frontend)**: no code change required (`renderTextWithTerms` already derives all highlighting from `Object.keys(terms)`) — but 08 should be aware the *set* of glossary keys is now lowercase literal aliases rather than the dictionary's Title-Case canonical forms, and that `GlossaryTerm.source` may now read `"Proposed by the glossary curation model (not from a fixed dictionary)"` (PRD §6, both cosmetic, not required for correctness).
- Not from this PRD's own file scope, but flagged by the PRD for whoever consumes it: model-proposed glossary definitions are explicitly **not** routed through 05's fidelity reviewer (PRD §9's `[RESOLVED]` departure from the brief's own §5 open-risk table) — nothing for 05 to implement here, recorded only so it isn't rediscovered as a perceived gap.

## Summary of what requires you (not a dev agent)

Per PRD §8, all four items are session-local judgment calls or live-infrastructure checks that cannot be automated by a dev agent:

1. **Review the stoplist prune's diff (Task 5) before treating it as final.** Read the script's printed drop list (14 dropped terms + first 70 characters of each definition) and confirm none is jargon in a clinical context the tool didn't anticipate. Pay particular attention to `"foot, feet"`, flagged by the PRD as borderline.
2. **Extend `common_word_stoplist.json` beyond the 14-word starter list** if the review above surfaces more everyday words worth pruning — the PRD deliberately left the full ~100-300 word list as a data-curation pass, not something hand-authored inside the PRD or this task list (§9 `[DEFERRED]`).
3. **Prompt smoke test against 2-3 real or de-identified notes**, once 06 wires `curate_glossary_terms` into the live pipeline (ngrok + pm2, `SERVICE_MODE=combined`): confirm (a) a genuinely common word gets dropped; (b) a note containing one of the seven named gap-terms (`calcified`, `contrast`, `angiogram`, `narrowing`, `circumflex`, `electrocardiogram`, `statin`) gets it proposed with a plain-language definition and `source: "llm_proposed"`; (c) the proposed term's `matched_term` actually appears verbatim in the rendered care plan text, so it highlights in the UI once 08 lands.
4. **Check the readability score on the first real end-to-end run for label-field skew**, once 06 produces a real before/after score against actual pipeline output — `render_care_plan_text` deliberately includes short, non-sentence label fields (titles, dosage strings, timeframes); spot-check whether the "after" score reads as visibly skewed by these versus what a prose-only projection would have scored, and if so, narrow the field list for the readability consumer specifically (the escape hatch PRD §9 already specifies, not a design decision left open here).

No PRD §9 items are `[OPEN]` — every item is `[RESOLVED]` or explicitly `[DEFERRED]` to a data-curation/manual-check step (items 2 and 4 above); the gate was clear, and all 11 tasks above derive from `[RESOLVED]` decisions only. One material implementation fact was discovered while grounding these tasks in the real codebase and is not itself a PRD gap: deleting `build_glossary_from_simplified_text` (Task 9, required by PRD §4.6) breaks `care_plan/pipeline.py`'s module import — and everything that transitively imports it, including `app.py` — until 06 rewires the call site. This is disclosed in full in Task 9 and carved out precisely in Task 11; it is a materially larger blast radius than PRD 04's own analogous (call-time-only) gap, so whoever sequences the actual `dev-code` runs for 07 and 06 should treat them as landing back-to-back, with no full-suite CI gate expected to pass in between — the same operational treatment the project's own README already applies to PRD 04 and 06.
