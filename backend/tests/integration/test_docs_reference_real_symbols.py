"""
tests/integration/test_docs_reference_real_symbols.py — Guard against doc/code drift.

Three narrowly-scoped, symbol-existence checks against the shipped content of
docs/pipeline.md and docs/architecture.md (PRD 16 §4.6): a doc that names a
prompt filename, a pipeline-step label, or a JobDoc field must name a real one.
These are presence checks only — they do not assert the surrounding prose is
correct, only that the symbols it names actually exist in the checked-out code.
"""

import pathlib
import re

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
DOCS_DIR = REPO_ROOT / "docs"
PROMPTS_DIR = BACKEND_DIR / "care_plan" / "prompts"


def test_prompt_filenames_in_pipeline_doc_exist():
    """Every backtick-quoted `*.txt` prompt filename named in pipeline.md must be
    a real file under backend/care_plan/prompts/."""
    text = (DOCS_DIR / "pipeline.md").read_text()
    filenames = set(re.findall(r"`([a-z_]+\.txt)`", text))
    assert filenames, "expected at least one prompt filename referenced in docs/pipeline.md"
    missing = {f for f in filenames if not (PROMPTS_DIR / f).is_file()}
    assert not missing, (
        f"docs/pipeline.md references prompt file(s) not found under {PROMPTS_DIR}: "
        f"{sorted(missing)}"
    )


def test_pipeline_step_labels_appear_in_pipeline_doc():
    """Constants.Pipeline.PIPELINE_STEPS must have 6 members, and every member's
    patient-facing `.label` must appear verbatim somewhere in pipeline.md."""
    from utils.constants import Constants

    steps = list(Constants.Pipeline.PIPELINE_STEPS)
    assert len(steps) == 6, f"expected 6 pipeline steps, found {len(steps)}: {steps}"

    text = (DOCS_DIR / "pipeline.md").read_text()
    missing = [step.label for step in steps if step.label not in text]
    assert not missing, f"docs/pipeline.md is missing pipeline-step label(s): {missing}"


def test_job_doc_fields_named_in_architecture_doc_are_real():
    """Every field name architecture.md's 'Job document as a state machine' section
    lists must be a real key in JobDoc.model_fields."""
    from models.job import JobDoc

    text = (DOCS_DIR / "architecture.md").read_text()
    match = re.search(r"Key fields, matching.*?\.\n", text, re.S)
    assert match, "expected a 'Key fields, matching ...' sentence in docs/architecture.md"

    paragraph = match.group(0)
    named_fields = set(re.findall(r"`([a-z][a-z_]*)`", paragraph))
    assert named_fields, "found no backtick-quoted field names in the 'Key fields' sentence"

    real_fields = set(JobDoc.model_fields.keys())
    missing = named_fields - real_fields
    assert not missing, (
        f"docs/architecture.md's 'Job document as a state machine' section names "
        f"field(s) not on JobDoc: {sorted(missing)}"
    )
