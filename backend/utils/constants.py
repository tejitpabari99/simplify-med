from enum import Enum, StrEnum


class _GradingMethodBase:
    def __init__(self, value: str, description: str):
        self.value = value
        self.description = description


class Constants:

    class Schema:
        INPUT_VERSION: str = "1.0"
        GRADING_VERSION: str = "1.0"
        CARE_PLAN_VERSION: str = "1.2"

    class Uploads:
        IMAGE_EXTENSIONS: frozenset[str] = frozenset({"png", "jpg", "jpeg", "webp", "heic"})
        ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
            {"pdf", "txt", "docx", "html", "htm"} | IMAGE_EXTENSIONS
        )

        class SourceKind(StrEnum):
            """Where a job's input text came from. The only two shapes this
            single-flow app ever produces (see routes/jobs.py)."""
            TEXT   = "text"
            UPLOAD = "upload"

        # Upper bound on extracted/pasted document text, enforced up front
        # (routes/jobs.py, services.care_plan_input) before any job is
        # enqueued. Not a practical limit on real clinical documents (even a
        # long chart is well under 100K chars) -- exists only to fail fast on
        # a pathological input, with enormous headroom below the model's
        # input context. The output ceiling is Llm.MAX_TOKENS_LONG_FORM, not this.
        MAX_TEXT_LENGTH: int = 500_000

        # UTF-8-encoded BYTE budget, enforced alongside MAX_TEXT_LENGTH (char
        # count alone doesn't bound bytes for non-ASCII text). HAZARD: sized
        # to keep the full care_plan_outputs Firestore doc under the 1,048,576
        # byte (1 MiB) hard document limit -- Firestore measures size in
        # UTF-8 bytes, not codepoints, so e.g. 500K CJK chars is ~1.5 MB.
        # Exceeding this previously caused an uncaught Firestore write
        # failure (500) instead of a clean 400 (edge-case review Finding 1).
        # 350,000 B leaves a large safety margin below the ~896,576 B
        # actually available for input_text once job metadata and the
        # trimmed output_data reserve are accounted for -- do not raise this
        # without re-deriving that budget.
        MAX_TEXT_BYTES: int = 350_000

        # Minimum stripped-text length (chars) for a file/document to count
        # as real content rather than noise. Applied in
        # services.care_plan_input.resolve_uploaded_files and again
        # defensively in routes/worker.py before any LLM step runs. Without
        # this floor, a scanned/no-text-layer PDF or blank file could
        # silently reach the pipeline and produce a fabricated "completed"
        # care plan instead of failing with EMPTY_DOCUMENT (edge-case review
        # Finding 2).
        MIN_MEANINGFUL_CONTENT_CHARS: int = 20

    class Pipeline:
        PIPELINE_VERSION: str = "v1-2"

        class PIPELINE_STEPS(Enum):
            """Named steps of the care-plan pipeline. Each member carries its
            1-based step number (`.number`) and its user-facing progress label
            (`.label`); replaces the old bare `dict[int, str]` so call sites
            reference named members instead of int literals."""
            READ_NOTE          = (1, "Reading your note")
            DETECT_TERMS       = (2, "Finding difficult and medical terms")
            SIMPLIFY_LANGUAGE  = (3, "Simplifying language")
            CLARIFY_AND_ACTION = (4, "Clarifying actions and numbers")
            STRUCTURE_DOCUMENT = (5, "Organizing your care plan")

            def __new__(cls, number: int, label: str):
                obj = object.__new__(cls)
                obj._value_ = number
                obj.number = number
                obj.label = label
                return obj

    class Limits:
        MAX_FILE_COUNT: int = 5
        # Aggregate upload cap: 5 files / 10 MB combined / NO per-file cap (an
        # explicit product decision -- deliberately more permissive per file,
        # tighter in aggregate). Mirrors frontend/src/utils/validateFiles.ts's
        # MAX_AGGREGATE_BYTES -- keep these two values in sync.
        MAX_AGGREGATE_FILE_BYTES: int = 10 * 1024 * 1024
        RATE_LIMIT_PER_IP_PER_HOUR: int = 5
        RATE_LIMIT_COLLECTION: str = "rate_limits"
        RATE_LIMIT_COUNTER_TTL_HOURS: int = 2
        JOB_TTL_HOURS: int = 1
        # Number of trusted reverse-proxy hops between the public internet and
        # this container -- i.e. how many IPs are Google-appended to the RIGHT
        # end of X-Forwarded-For before the request reaches Flask. See the
        # topology note on utils.rate_limit.get_client_ip for why this is 1
        # today (direct Cloud Run, no external Load Balancer) and when it
        # would need to change. Overridable via TRUSTED_PROXY_HOPS so a
        # future topology change doesn't require a code change.
        TRUSTED_PROXY_HOPS: int = 1

    class Deadlines:
        SINGLE_JOB_INTERNAL_DEADLINE_S: int = 270
        JOB_TIMEOUT_SECONDS_SINGLE: int = 300

    class Llm:
        MODEL_DEFAULT: str = "gemini-1.5-pro"
        MAX_TOKENS: int = 8192
        MAX_TOKENS_LONG_FORM: int = 65536
        TEMPERATURE_TEXT: float = 0.3
        TEMPERATURE_JSON: float = 0.2
        IMAGE_OCR_PROMPT: str = (
            "You are extracting clinical text from a photographed or scanned medical "
            "document image.\n\n"
            "Transcribe ALL visible text from the image exactly as written, preserving:\n"
            "- Section headers and structure, as plain text (no markdown, no HTML)\n"
            "- Medication names, dosages, frequencies, and instructions verbatim\n"
            "- Dates, numbers, units, and clinician/patient names exactly as they appear\n"
            "- Line breaks between distinct sections, list items, or table rows\n\n"
            "Do not summarize, interpret, correct, or add any text that is not visibly "
            "present in the image. Do not describe the image (for example, never write "
            "\"this is a photo of...\"). Output ONLY the transcribed text.\n\n"
            "If the image contains no legible text at all (blank, illegibly blurry, or a "
            "non-document photo), respond with exactly this token and nothing else:\n"
            "NO_TEXT_FOUND"
        )

    class Storage:
        GCS_BUCKET_ENV_VAR: str = "GCP_BUCKET_NAME"

    class Grading:
        class GRADING_METHODS(Enum):
            SMOG           = _GradingMethodBase("SMOG", "SMOG (McLaughlin 1969) — counts polysyllabic words; designed for health materials")
            FLESCH_KINCAID = _GradingMethodBase("Flesch-Kincaid", "Flesch-Kincaid Reading Ease + Grade Level (1975) — sentence length × syllable load")
            DALE_CHALL     = _GradingMethodBase("Dale-Chall", "Dale-Chall (1948/1995) — difficult words outside the 3,000 familiar-word list")
            PEMAT          = _GradingMethodBase("PEMAT", "PEMAT (AHRQ 2013) — automated approximation of items 3,8,14,21-22 (understandability) and 27-33 (actionability)")
            SAM            = _GradingMethodBase("SAM", "SAM (Doak et al. 1996) — automated approximation of content, literacy demand, and layout/typography domains")
            CDC_CCI        = _GradingMethodBase("CDC CCI", "CDC Clear Communication Index — automated approximation of main message, behavioral recommendations, numbers, and call-to-action items")

    class Enums:
        class SOURCE(Enum):
            DOCUMENTS = "documents"
            RECORDING = "recording"
            NOTES     = "notes"

        class IMPORTANCE(Enum):
            HIGH = "high"
            LOW  = "low"

    class EnvVars:
        GCS_BUCKET: str = "GCP_BUCKET_NAME"
        GCP_PROJECT_ID: str = "GCP_PROJECT_ID"
        GCP_LOCATION: str = "GCP_LOCATION"
        VERTEX_AI_MODEL: str = "VERTEX_AI_MODEL"
        FIRESTORE_DATABASE_ID: str = "FIRESTORE_DATABASE_ID"
        K_SERVICE: str = "K_SERVICE"
        SERVICE_VERSION: str = "SERVICE_VERSION"
        WORKER_VERIFY_OIDC: str = "WORKER_VERIFY_OIDC"
        WORKER_SERVICE_ACCOUNT: str = "WORKER_SERVICE_ACCOUNT"
        CLOUD_TASKS_QUEUE: str = "CLOUD_TASKS_QUEUE"
        WORKER_URL: str = "WORKER_URL"
        PORT: str = "PORT"
        FLASK_ENV: str = "FLASK_ENV"
        SERVICE_MODE: str = "SERVICE_MODE"
        TRUSTED_PROXY_HOPS: str = "TRUSTED_PROXY_HOPS"

    class Observability:
        SERVICE_NAME_DEFAULT: str = "backend-processing"
        LOG_EXTRA_KEYS: list[str] = [
            "user_id", "function", "care_plan_version", "grading_version", "input_version",
            "operation", "metric", "metric_type", "duration_ms", "success", "outcome",
            "step_name", "status", "http_method", "http_path", "http_status",
            "http_status_code", "total_duration_ms", "saved_id", "input_chars",
            "error", "labels", "duration_ms_observed", "OpOutcome",
            "service", "environment",
        ]
        DIM_OUTCOME: str = "OpOutcome"
        DIM_STATUS_CODE: str = "StatusCode"
        DIM_CORRELATION_ID: str = "CorrelationId"
