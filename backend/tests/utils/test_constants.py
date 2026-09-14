from utils.constants import Constants


def test_schema_namespace():
    assert Constants.Schema.INPUT_VERSION == "1.0"
    assert Constants.Schema.GRADING_VERSION == "1.0"
    assert Constants.Schema.CARE_PLAN_VERSION == "1.2"


def test_uploads_namespace():
    assert "pdf" in Constants.Uploads.ALLOWED_EXTENSIONS
    # Generous by design (no practical limit on real clinical documents) --
    # see the constant's own comment for the reasoning. Must stay comfortably
    # below what fits in the model's input context.
    assert Constants.Uploads.MAX_TEXT_LENGTH == 500_000
    assert Constants.Uploads.MIN_MEANINGFUL_CONTENT_CHARS == 20


def test_uploads_source_kind_enum():
    sk = Constants.Uploads.SourceKind
    assert sk.TEXT == "text"
    assert sk.UPLOAD == "upload"


def test_limits_namespace_upload_and_rate_limits():
    assert Constants.Limits.MAX_FILE_COUNT == 5
    assert Constants.Limits.MAX_AGGREGATE_FILE_BYTES == 10 * 1024 * 1024
    assert Constants.Limits.RATE_LIMIT_PER_IP_PER_HOUR == 5
    assert Constants.Limits.RATE_LIMIT_COLLECTION == "rate_limits"
    assert Constants.Limits.RATE_LIMIT_COUNTER_TTL_HOURS == 2
    assert Constants.Limits.JOB_TTL_HOURS == 1
    assert Constants.Limits.TRUSTED_PROXY_HOPS == 1


def test_deadlines_namespace():
    assert Constants.Deadlines.SINGLE_JOB_INTERNAL_DEADLINE_S == 270
    assert Constants.Deadlines.JOB_TIMEOUT_SECONDS_SINGLE == 300


def test_llm_namespace():
    assert Constants.Llm.MODEL_DEFAULT == "gemini-1.5-pro"
    assert Constants.Llm.TEMPERATURE_TEXT == 0.3
    assert Constants.Llm.TEMPERATURE_JSON == 0.2
    assert Constants.Llm.MAX_TOKENS == 8192
    assert Constants.Llm.MAX_TOKENS_LONG_FORM == 65536


def test_storage_namespace():
    assert Constants.Storage.GCS_BUCKET_ENV_VAR == "GCP_BUCKET_NAME"


def test_observability_namespace():
    assert Constants.Observability.SERVICE_NAME_DEFAULT == "backend-processing"
    assert "user_id" in Constants.Observability.LOG_EXTRA_KEYS
    assert "extraction_signal" in Constants.Observability.LOG_EXTRA_KEYS
    assert "extraction_signal_facts" in Constants.Observability.LOG_EXTRA_KEYS
    assert Constants.Observability.DIM_OUTCOME == "OpOutcome"


def test_env_vars_namespace():
    assert Constants.EnvVars.GCS_BUCKET == "GCP_BUCKET_NAME"
    assert Constants.EnvVars.GCP_PROJECT_ID == "GCP_PROJECT_ID"
    assert Constants.EnvVars.VERTEX_AI_MODEL == "VERTEX_AI_MODEL"
    assert Constants.EnvVars.FIRESTORE_DATABASE_ID == "FIRESTORE_DATABASE_ID"
    assert Constants.EnvVars.WORKER_VERIFY_OIDC == "WORKER_VERIFY_OIDC"
    assert Constants.EnvVars.WORKER_SERVICE_ACCOUNT == "WORKER_SERVICE_ACCOUNT"
    assert Constants.EnvVars.CLOUD_TASKS_QUEUE == "CLOUD_TASKS_QUEUE"
    assert Constants.EnvVars.WORKER_URL == "WORKER_URL"


def test_pipeline_steps_enum():
    steps = Constants.Pipeline.PIPELINE_STEPS
    assert [m.name for m in steps] == [
        "READ_NOTE", "DETECT_TERMS", "GROUND", "ASSEMBLE_AND_RENDER", "REVIEW", "CORRECT",
    ]
    assert steps.READ_NOTE.number == 1
    assert steps.READ_NOTE.label == "Reading your note"
    assert steps.DETECT_TERMS.number == 2
    assert steps.DETECT_TERMS.label == "Finding difficult and medical terms"
    assert steps.GROUND.number == 3
    assert steps.GROUND.label == "Finding the facts in your note"
    assert steps.ASSEMBLE_AND_RENDER.number == 4
    assert steps.ASSEMBLE_AND_RENDER.label == "Putting your care plan together"
    assert steps.REVIEW.number == 5
    assert steps.REVIEW.label == "Double-checking your care plan"
    assert steps.CORRECT.number == 6
    assert steps.CORRECT.label == "Finishing touches"
    retired_step_names = (
        "SIMPLIFY" + "_LANGUAGE",
        "CLARIFY" + "_AND_ACTION",
        "STRUCTURE" + "_DOCUMENT",
    )
    assert all(not hasattr(steps, name) for name in retired_step_names)


def test_pipeline_version_constants():
    assert Constants.Pipeline.PIPELINE_VERSION == "v1-2"


def test_grading_methods_enum():
    methods = Constants.Grading.GRADING_METHODS
    assert methods.SMOG.value.value == "SMOG"
    assert methods.PEMAT.value.value == "PEMAT"
