"""services/care_plan_input.py — input resolution and storage for the care-plan
pipeline: GCS upload, file-type validation, text extraction, and multi-file
resolution."""

import io
import logging
import os
import uuid

import PyPDF2.errors

from utils.constants import Constants
from utils.gcs import get_gcs_bucket
from utils.image_ocr import extract_text_from_image
from utils.misc import extract_text_from_html, source_separator, text_artifact_filename
from utils.pdf import merge_pdfs, extract_text_from_pdf
from models.input import ResolvedInput
from errors import ErrorCode, SimplifyError

logger = logging.getLogger(__name__)


def upload_combined_pdf(pdf_bytes: bytes, user_id: str) -> str:
    """Upload combined input PDF bytes and return a gs:// URI. Uses a visually
    distinct prefix (care_plan_inputs/) so a GCS lifecycle rule can safely
    target these uploads for retention."""
    bucket_name = os.environ.get(Constants.Storage.GCS_BUCKET_ENV_VAR, "")
    if not bucket_name:
        raise RuntimeError("GCP_BUCKET_NAME is not configured")

    object_id = str(uuid.uuid4())
    blob_name = f"care_plan_inputs/{user_id}/inputs/{object_id}.pdf"

    bucket = get_gcs_bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(pdf_bytes, content_type="application/pdf")
    return f"gs://{bucket_name}/{blob_name}"


def _get_extension(filename: str) -> str:
    """Return the lowercased extension of filename, or "" if it has no dot.

    Centralizes extension parsing so callers never call ``rsplit(".", 1)[1]``
    directly on a filename that might be dot-less (which raises IndexError).
    """
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].lower()


def is_allowed_extension(filename: str) -> bool:
    ext = _get_extension(filename)
    return bool(ext) and ext in Constants.Uploads.ALLOWED_EXTENSIONS


def validate_text_storable(text: str, *, field: str = "Text") -> None:
    """Raise ValueError with a clear, user-safe message if `text` contains
    characters Firestore cannot store as a UTF-8-encoded string field.

    Covers:
    - Lone (unpaired) UTF-16 surrogate codepoints (U+D800-U+DFFF). JSON's
      \\uXXXX escape permits encoding these even though they are not valid
      Unicode scalar values, so `json.loads('{"text": "\\ud800"}')` happily
      produces a Python str containing one -- but such a str cannot be
      UTF-8-encoded, and Firestore's client eventually needs to do exactly
      that (over gRPC/protobuf) to write it. Without this check, that
      failure is an uncaught UnicodeEncodeError deep inside create_job_doc's
      `.set(payload)` (see edge-case review Finding 5).
    - Embedded NUL bytes (U+0000), which Firestore/protobuf string fields
      also cannot store.

    Called from validate_extracted_text_length (so every caller of that
    function gets this for free) and per-file inside resolve_uploaded_files
    (so a single bad file can be identified/skipped under
    tolerate_unusable_files rather than failing the whole request).
    """
    try:
        text.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError(
            f"{field} contains characters that cannot be saved (invalid Unicode, "
            "e.g. an unpaired surrogate). This can happen with corrupted clipboard "
            "paste or OCR output -- try re-typing or re-uploading the affected content."
        ) from exc
    if "\x00" in text:
        raise ValueError(f"{field} contains a null byte, which cannot be saved.")


def validate_extracted_text_length(text: str) -> None:
    """Raise ValueError if extracted or pasted document text is unsafe to
    store, or exceeds the configured maximum length.

    Applied to the pasted-text path in routes/jobs.py::_resolve_job_input,
    as well as to text extracted from an upload. Callers must invoke this
    before enqueueing a job, so an over-limit or unstorable document is
    rejected at submission time with a clear, accurate reason instead of
    failing deep into the pipeline (e.g. via ErrorCode.LLM_MAX_TOKENS, an
    unrelated output-token-cap error) or with an uncaught Firestore write
    failure.

    Two independent length checks, both must pass:
    - MAX_TEXT_LENGTH: a Python character (codepoint) count. The original
      check; kept as-is so ASCII-only input's allowed length is unchanged.
    - MAX_TEXT_BYTES: a UTF-8-encoded byte count. Added because Firestore's
      1,048,576-byte (1 MiB) per-document hard limit is a *byte* limit, and
      the char count alone doesn't bound it for non-ASCII text -- 500,000
      chars of CJK/emoji is 1.5-2 MB in UTF-8, well past the char check
      failing to catch it (see Constants.Uploads.MAX_TEXT_BYTES for the full
      accounting, and edge-case review Finding 1).
    """
    validate_text_storable(text, field="Extracted document text")

    char_length = len(text)
    if char_length > Constants.Uploads.MAX_TEXT_LENGTH:
        raise ValueError(
            f"Extracted document text is too long to process "
            f"({char_length:,} characters; limit is {Constants.Uploads.MAX_TEXT_LENGTH:,} characters). "
            "Try uploading a shorter document or splitting it into smaller sections."
        )

    byte_length = len(text.encode("utf-8"))
    if byte_length > Constants.Uploads.MAX_TEXT_BYTES:
        raise ValueError(
            f"Extracted document text is too long to process "
            f"({byte_length:,} bytes when encoded; limit is {Constants.Uploads.MAX_TEXT_BYTES:,} bytes). "
            "Try uploading a shorter document or splitting it into smaller sections."
        )


def extract_text_from_bytes(file_bytes: bytes, filename: str) -> str:
    """Extract plain text from PDF, TXT, DOCX, HTML, or image bytes."""
    ext = _get_extension(filename)

    if not ext:
        raise SimplifyError(ErrorCode.UNSUPPORTED_FILE_TYPE, detail=f"filename has no extension: {filename}")

    if ext == "txt":
        return file_bytes.decode("utf-8", errors="replace")

    if ext == "pdf":
        try:
            return extract_text_from_pdf(file_bytes)
        except PyPDF2.errors.FileNotDecryptedError as exc:
            # Verified against the actual installed PyPDF2 3.0.1: a genuinely
            # password-protected PDF raises this specific subclass. None of
            # PyPDF2's exceptions are ValueError/FileNotFoundError/SimplifyError,
            # so uncaught they fall through to a generic 500 (edge-case review
            # Finding 6). Distinguish the "encrypted" case from "corrupt" so
            # the user gets an actionable, specific message.
            raise SimplifyError(
                ErrorCode.FILE_PARSE_FAILED,
                detail=f"{filename} appears to be password-protected. Please upload an unencrypted PDF.",
                original=exc,
            ) from exc
        except PyPDF2.errors.PyPdfError as exc:
            # Base class of every other PyPDF2 read failure (EmptyFileError
            # for a zero-byte file, PdfReadError for garbage bytes / a
            # mislabeled non-PDF extension, PdfStreamError, etc.) -- all
            # verified to raise from this call for the corresponding inputs.
            raise SimplifyError(
                ErrorCode.FILE_PARSE_FAILED,
                detail=f"{filename} could not be read -- it may be corrupted, empty, "
                       f"or not actually a PDF file ({type(exc).__name__}).",
                original=exc,
            ) from exc

    if ext == "docx":
        try:
            from docx import Document
        except ImportError as exc:
            raise RuntimeError(
                "python-docx is not installed. Add 'python-docx' to requirements.txt."
            ) from exc

        try:
            doc = Document(io.BytesIO(file_bytes))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except RuntimeError:
            raise
        except Exception as exc:
            # python-docx raises whatever the underlying zip/XML parser raises
            # for a corrupt or non-DOCX file (zipfile.BadZipFile, KeyError for
            # a missing part, docx.opc.exceptions.PackageNotFoundError, etc.) --
            # none of these are SimplifyError/ValueError, so uncaught they fall
            # through to a generic 500 (see edge-case review Finding 6, which
            # verified the equivalent PyPDF2 gap; python-docx is the same
            # class of bug). Reclassify as a clean, actionable FILE_PARSE_FAILED.
            raise SimplifyError(
                ErrorCode.FILE_PARSE_FAILED,
                detail=f"{filename} could not be read as a DOCX file -- it may be "
                       f"corrupted or not actually a DOCX file ({type(exc).__name__}).",
                original=exc,
            ) from exc

    if ext in {"html", "htm"}:
        try:
            return extract_text_from_html(file_bytes)
        except Exception as exc:
            # BeautifulSoup's stdlib html.parser backend is extremely lenient
            # and rarely raises, but guard the boundary anyway for defense in
            # depth/symmetry with the other extractors (Finding 6).
            raise SimplifyError(
                ErrorCode.FILE_PARSE_FAILED,
                detail=f"{filename} could not be read as an HTML file ({type(exc).__name__}).",
                original=exc,
            ) from exc

    if ext in Constants.Uploads.IMAGE_EXTENSIONS:
        return extract_text_from_image(file_bytes, ext)

    raise SimplifyError(ErrorCode.UNSUPPORTED_FILE_TYPE, detail=f"extension: {ext}")


def resolve_uploaded_files(
    uploads,
    *,
    max_file_count: int,
    max_aggregate_bytes: int,
    tolerate_unusable_files: bool = False,
) -> tuple[ResolvedInput, bytes | None]:
    """Resolve a list of uploaded files into combined text (+ an optional
    merged PDF for storage).

    max_file_count/max_aggregate_bytes are the caller's own upload limits
    (routes/jobs.py passes Constants.Limits: max 5 files, 10 MB aggregate,
    no per-file cap -- an explicit product decision).

    tolerate_unusable_files: when True, a single file that is individually
    unusable -- unsupported extension, corrupt/encrypted (Finding 6),
    unstorable text (Finding 5), or no meaningful extractable content
    (Finding 2/EMPTY_DOCUMENT, e.g. a scanned/no-text-layer PDF) -- is
    skipped rather than aborting the whole request; its filename is recorded
    in the returned ResolvedInput.skipped_files. The request only fails if
    NO file yields usable content. When False, one bad file among several
    aborts the whole request (Finding 8).

    Request-level constraints (file count, aggregate byte limit) are never
    tolerated regardless of this flag -- those are hard stops on the request
    itself, not a per-file quality issue a skip can fix. There is no
    per-file byte limit -- only the aggregate cap applies.
    """
    files = [upload for upload in uploads if upload and upload.filename]
    if not files:
        raise ValueError("Uploaded file is missing a filename")
    if len(files) > max_file_count:
        raise ValueError(f"Upload supports at most {max_file_count} files")

    text_parts: list[str] = []
    merge_candidates: list[tuple[bytes, str]] = []
    filenames: list[str] = []
    skipped_files: list[str] = []
    # Parallel to skipped_files: the actual exception raised for each
    # skipped file, so a single-file request that fails can re-raise its
    # own specific, already-classified error (see the `not filenames` check
    # below) instead of always collapsing to a generic EMPTY_DOCUMENT.
    skipped_errors: list[Exception] = []
    aggregate_bytes = 0

    for upload in files:
        filename = upload.filename

        # Extension check happens before reading bytes (as before this
        # change) so an unsupported file never counts toward the byte/
        # aggregate limits below -- still tolerable (skippable) under
        # tolerate_unusable_files, same as an extraction failure.
        if not is_allowed_extension(filename):
            exc = ValueError("File must be PDF, TXT, DOCX, HTML, or an image (PNG/JPG/WEBP/HEIC)")
            if tolerate_unusable_files:
                logger.warning("care_plan_input: skipping unusable file %s: %s", filename, exc)
                skipped_files.append(filename)
                skipped_errors.append(exc)
                continue
            raise exc

        file_bytes = upload.read()
        # Request-level hard stop: never tolerated, regardless of
        # tolerate_unusable_files -- skipping a file doesn't "give back" the
        # bytes it already consumed against the request's own size budget.
        aggregate_bytes += len(file_bytes)
        if aggregate_bytes > max_aggregate_bytes:
            limit_mb = max_aggregate_bytes / (1024 * 1024)
            raise ValueError(f"Combined file size is too large (max {limit_mb:g} MB total)")

        try:
            extracted_text = extract_text_from_bytes(file_bytes, filename)
            validate_text_storable(extracted_text, field=f"{filename}'s extracted text")
            real_content = extracted_text.strip()
            if len(real_content) < Constants.Uploads.MIN_MEANINGFUL_CONTENT_CHARS:
                # Mirrors the image-OCR EMPTY_DOCUMENT path for every other
                # format: a scanned/no-text-layer PDF, a blank docx/txt/html,
                # etc. must not silently become a non-empty "--- Source: ... ---"
                # scaffolding-only document that sails past every downstream
                # check (edge-case review Finding 2).
                raise SimplifyError(
                    ErrorCode.EMPTY_DOCUMENT,
                    detail=f"{filename} produced no meaningful extractable text (likely a "
                           "scanned image with no text layer, or a blank/empty file).",
                )
        except (SimplifyError, ValueError) as exc:
            if tolerate_unusable_files:
                logger.warning("care_plan_input: skipping unusable file %s: %s", filename, exc)
                skipped_files.append(filename)
                skipped_errors.append(exc)
                continue
            raise

        filenames.append(filename)
        text_parts.append(f"{source_separator(filename)}{real_content}")

        ext = _get_extension(filename)
        if ext in {"pdf", "txt"} or ext in Constants.Uploads.IMAGE_EXTENSIONS:
            merge_candidates.append((file_bytes, filename))
        elif ext in {"docx", "html", "htm"} and real_content:
            merge_candidates.append(
                (extracted_text.encode("utf-8"), text_artifact_filename(filename))
            )

    if not filenames:
        # Only reachable under tolerate_unusable_files (otherwise the loop
        # above would already have raised on the first unusable file) --
        # every uploaded file was individually unusable.
        if len(files) == 1 and skipped_errors:
            # A single-file request isn't really a "batch" -- collapsing its
            # one already-classified failure into the generic "none of
            # several files worked" EMPTY_DOCUMENT message would discard
            # actionable detail (e.g. a password-protected PDF would
            # misleadingly surface as "not a scanned image"). Re-raise the
            # original error instead (Finding 5/6).
            raise skipped_errors[0]
        raise SimplifyError(
            ErrorCode.EMPTY_DOCUMENT,
            detail="None of the uploaded files contained readable text.",
        )

    combined_text = "\n".join(text_parts).strip()
    # Fail fast: reject an over-limit document up front (before the (possibly
    # slow) PDF merge below, before any job is enqueued, and before any
    # pipeline/LLM step runs) rather than letting it run every pipeline step
    # only to fail late on an unrelated output-token-cap error.
    validate_extracted_text_length(combined_text)

    combined_pdf_bytes = None
    if merge_candidates:
        try:
            combined_pdf_bytes = merge_pdfs(merge_candidates)
        except Exception:
            logger.exception("care_plan_input: failed to merge input files - continuing without combined PDF")

    file_count = len(files)
    file_types = sorted({ext for f in files if (ext := _get_extension(f.filename))})

    source_filename = ", ".join(filenames)
    combined_pdf_size = float(len(combined_pdf_bytes)) if combined_pdf_bytes is not None else None
    return ResolvedInput(
        text=combined_text,
        source_description=source_filename,
        source_filename=source_filename,
        combined_pdf_size=combined_pdf_size,
        file_count=file_count,
        file_types=file_types,
        skipped_files=skipped_files,
    ), combined_pdf_bytes


def resolve_input_from_job_doc(job) -> str:  # job: models.job.JobDoc
    return job.input_text or ""
