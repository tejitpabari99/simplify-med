from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[2]


def test_pipeline_is_flattened_to_a_single_non_versioned_module():
    """This app hard-codes one pipeline: no versioned packages, no abstract
    base class, no version registry/factory."""
    assert not (BACKEND_DIR / "care_plan" / "v1").exists()
    assert not (BACKEND_DIR / "care_plan" / "v1_1").exists()
    assert not (BACKEND_DIR / "care_plan" / "v1_2").exists()
    assert not (BACKEND_DIR / "care_plan" / "interface.py").exists()

    pipeline_source = (BACKEND_DIR / "care_plan" / "pipeline.py").read_text()
    assert "class CarePlanPipeline:" in pipeline_source
    assert "ABC" not in pipeline_source
    assert "SimplifyPipeline" not in pipeline_source

    prompts_dir = BACKEND_DIR / "care_plan" / "prompts"
    assert (prompts_dir / "simplify_language.txt").is_file()
    assert (prompts_dir / "clarify_and_action.txt").is_file()
    assert (prompts_dir / "structure_note.txt").is_file()


def test_old_simplify_folder_is_gone():
    assert not (BACKEND_DIR / "simplify").exists()
