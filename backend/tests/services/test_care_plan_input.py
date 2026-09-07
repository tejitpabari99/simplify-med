"""tests/services/test_care_plan_input.py — regression tests for extension parsing
in services/care_plan_input.py.

Covers the dot-less-filename edge case: extension parsing must fail cleanly with
a SimplifyError rather than raising an unhandled IndexError from rsplit(".", 1)[1].
"""
import io
from unittest.mock import patch

import pytest

from services.care_plan_input import (
    extract_text_from_bytes,
    is_allowed_extension,
    resolve_uploaded_files,
    upload_combined_pdf,
    validate_extracted_text_length,
)
from errors import ErrorCode, SimplifyError
from utils.constants import Constants

# A minimal, valid 1x1 PNG (no network, no fixture file needed).
_ONE_PX_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082"
)


class _FakeUpload:
    """Minimal stand-in for a Werkzeug FileStorage: .filename + .read()."""

    def __init__(self, filename: str, data: bytes):
        self.filename = filename
        self._buf = io.BytesIO(data)

    def read(self):
        return self._buf.read()


def _resolve(uploads, **overrides):
    """resolve_uploaded_files with this app's only real limits
    (Constants.Limits) as the default, overridable per test."""
    kwargs = {
        "max_file_count": Constants.Limits.MAX_FILE_COUNT,
        "max_aggregate_bytes": Constants.Limits.MAX_AGGREGATE_FILE_BYTES,
    }
    kwargs.update(overrides)
    return resolve_uploaded_files(uploads, **kwargs)


def test_is_allowed_extension_rejects_dotless_filename():
    """A filename with no dot must be rejected, not raise."""
    assert is_allowed_extension("noextension") is False


def test_extract_text_from_bytes_dotless_filename_raises_simplify_error():
    """extract_text_from_bytes must raise a clean SimplifyError (not IndexError)
    when the filename has no extension."""
    with pytest.raises(SimplifyError) as exc_info:
        extract_text_from_bytes(b"some bytes", "noextension")

    assert exc_info.value.error_code == ErrorCode.UNSUPPORTED_FILE_TYPE


def test_extract_text_from_bytes_still_works_for_txt():
    """Well-formed filenames with extensions are unaffected by the fix."""
    assert extract_text_from_bytes(b"hello world", "notes.txt") == "hello world"


@patch("services.care_plan_input.extract_text_from_image")
def test_extract_text_from_bytes_dispatches_image_extensions_to_ocr(mock_extract_image):
    mock_extract_image.return_value = "ocr text"

    result = extract_text_from_bytes(b"bytes", "photo.png")

    mock_extract_image.assert_called_once_with(b"bytes", "png")
    assert result == "ocr text"


@pytest.mark.parametrize("ext", ["png", "jpg", "jpeg", "webp", "heic"])
def test_is_allowed_extension_accepts_all_image_extensions(ext):
    assert is_allowed_extension(f"x.{ext}") is True


@patch.dict("services.care_plan_input.os.environ", {"GCP_BUCKET_NAME": "bucket"})
@patch("services.care_plan_input.uuid.uuid4")
@patch("services.care_plan_input.get_gcs_bucket")
def test_upload_combined_pdf_uses_care_plan_inputs_gcs_path(mock_get_gcs_bucket, mock_uuid4):
    """The merged input PDF always lands under the care_plan_inputs/ prefix
    (see the GCS lifecycle-rule note on upload_combined_pdf's docstring)."""
    from unittest.mock import MagicMock

    mock_uuid4.return_value = "input-456"
    blob = MagicMock()
    bucket = mock_get_gcs_bucket.return_value
    bucket.blob.return_value = blob

    uri = upload_combined_pdf(b"%PDF", "user-1")

    assert uri == "gs://bucket/care_plan_inputs/user-1/inputs/input-456.pdf"
    mock_get_gcs_bucket.assert_called_once_with("bucket")
    bucket.blob.assert_called_once_with("care_plan_inputs/user-1/inputs/input-456.pdf")
    blob.upload_from_string.assert_called_once_with(b"%PDF", content_type="application/pdf")


@patch.dict("services.care_plan_input.os.environ", {}, clear=True)
def test_upload_combined_pdf_raises_when_bucket_not_configured():
    with pytest.raises(RuntimeError, match="GCP_BUCKET_NAME"):
        upload_combined_pdf(b"%PDF", "user-1")


@patch("services.care_plan_input.extract_text_from_image")
def test_resolve_uploaded_files_image_becomes_raw_merge_candidate(mock_extract_image):
    mock_extract_image.return_value = "Known OCR text from image"
    fake_upload = _FakeUpload("photo.png", _ONE_PX_PNG)

    resolved, combined_pdf_bytes = _resolve([fake_upload])

    assert "Known OCR text from image" in resolved.text
    assert combined_pdf_bytes is not None


# ---------------------------------------------------------------------------
# validate_extracted_text_length / resolve_uploaded_files up-front size check
# ---------------------------------------------------------------------------

def test_validate_extracted_text_length_accepts_text_at_char_limit():
    """ASCII text at the byte-cap boundary (MAX_TEXT_BYTES, the binding
    constraint for 1-byte-per-char text) must still be accepted -- proves the
    new byte cap doesn't shrink the previously-allowed ASCII length."""
    text = "a" * Constants.Uploads.MAX_TEXT_BYTES
    validate_extracted_text_length(text)  # must not raise


def test_validate_extracted_text_length_rejects_text_over_char_limit():
    text = "a" * (Constants.Uploads.MAX_TEXT_LENGTH + 1)
    with pytest.raises(ValueError, match="too long"):
        validate_extracted_text_length(text)


def test_validate_extracted_text_length_rejects_text_over_byte_limit():
    text = "a" * (Constants.Uploads.MAX_TEXT_BYTES + 1)
    with pytest.raises(ValueError, match="too long"):
        validate_extracted_text_length(text)


def test_validate_extracted_text_length_rejects_cjk_text_under_char_cap_but_over_byte_cap():
    """Regression for edge-case review Finding 1: CJK text well under the
    500,000-character cap (so the old char-only check would have passed it)
    is 3 bytes/char in UTF-8, so it can exceed MAX_TEXT_BYTES while staying
    far under MAX_TEXT_LENGTH -- and must now be rejected by the byte check."""
    char_count = (Constants.Uploads.MAX_TEXT_BYTES // 3) + 100
    assert char_count < Constants.Uploads.MAX_TEXT_LENGTH
    text = "中" * char_count  # CJK character, 3 bytes each in UTF-8
    with pytest.raises(ValueError, match="too long"):
        validate_extracted_text_length(text)


def test_validate_extracted_text_length_rejects_lone_surrogate():
    """Regression for Finding 5: a lone UTF-16 surrogate can't be UTF-8
    encoded; must be rejected with a clean ValueError, not an uncaught
    UnicodeEncodeError deep inside Firestore's client."""
    with pytest.raises(ValueError, match="cannot be saved"):
        validate_extracted_text_length("hello \ud800 world")


def test_validate_extracted_text_length_rejects_null_byte():
    with pytest.raises(ValueError, match="null byte"):
        validate_extracted_text_length("hello \x00 world")


def test_resolve_uploaded_files_rejects_extracted_text_over_limit():
    """Regression: the uploaded-file path never checked extracted text length
    at all (unlike the pasted-text path), so an over-limit document would run
    every pipeline step before failing late with a misleading MAX_TOKENS
    error. It must now be rejected up front, before any job is created."""
    oversized_text = "a" * (Constants.Uploads.MAX_TEXT_BYTES + 1)
    fake_upload = _FakeUpload("notes.txt", oversized_text.encode("utf-8"))

    with pytest.raises(ValueError, match="too long"):
        _resolve([fake_upload])


# ---------------------------------------------------------------------------
# Minimum meaningful content (Finding 2 -- scanned/no-text-layer bypass)
# ---------------------------------------------------------------------------

def test_resolve_uploaded_files_blank_txt_raises_empty_document():
    """A blank/whitespace-only txt file must raise EMPTY_DOCUMENT rather than
    silently becoming a non-empty '--- Source: ... ---'-only document."""
    fake_upload = _FakeUpload("blank.txt", b"   \n\n  ")
    with pytest.raises(SimplifyError) as exc_info:
        _resolve([fake_upload])
    assert exc_info.value.error_code == ErrorCode.EMPTY_DOCUMENT


def test_resolve_uploaded_files_near_empty_txt_below_min_content_raises_empty_document():
    """A handful of stray characters (well under MIN_MEANINGFUL_CONTENT_CHARS)
    also counts as "no real content", not just a literal empty string."""
    fake_upload = _FakeUpload("blank.txt", b"x")
    with pytest.raises(SimplifyError) as exc_info:
        _resolve([fake_upload])
    assert exc_info.value.error_code == ErrorCode.EMPTY_DOCUMENT


def test_resolve_uploaded_files_accepts_text_at_min_content_length():
    text = "a" * Constants.Uploads.MIN_MEANINGFUL_CONTENT_CHARS
    fake_upload = _FakeUpload("notes.txt", text.encode("utf-8"))
    resolved, _ = _resolve([fake_upload])
    assert text in resolved.text


# ---------------------------------------------------------------------------
# tolerate_unusable_files (multi-file tolerance -- Finding 8)
# ---------------------------------------------------------------------------

def test_resolve_uploaded_files_non_tolerant_mode_aborts_on_first_bad_file():
    """Default (non-tolerant) behavior: one bad file among several aborts
    the whole request."""
    good = _FakeUpload("good.txt", b"This is a perfectly good clinical note.")
    blank = _FakeUpload("blank.txt", b"   ")
    with pytest.raises(SimplifyError) as exc_info:
        _resolve([good, blank])
    assert exc_info.value.error_code == ErrorCode.EMPTY_DOCUMENT


def test_resolve_uploaded_files_tolerant_mode_skips_bad_file_and_keeps_good_ones():
    good = _FakeUpload("good.txt", b"This is a perfectly good clinical note.")
    blank = _FakeUpload("blank.txt", b"   ")

    resolved, _ = _resolve([good, blank], tolerate_unusable_files=True)

    assert "perfectly good clinical note" in resolved.text
    assert resolved.skipped_files == ["blank.txt"]


def test_resolve_uploaded_files_tolerant_mode_raises_empty_document_when_all_files_bad():
    blank1 = _FakeUpload("blank1.txt", b"   ")
    blank2 = _FakeUpload("blank2.txt", b"")

    with pytest.raises(SimplifyError) as exc_info:
        _resolve([blank1, blank2], tolerate_unusable_files=True)
    assert exc_info.value.error_code == ErrorCode.EMPTY_DOCUMENT


def test_resolve_uploaded_files_tolerant_mode_skips_unsupported_extension():
    good = _FakeUpload("good.txt", b"This is a perfectly good clinical note.")
    bad_ext = _FakeUpload("virus.exe", b"whatever")

    resolved, _ = _resolve([good, bad_ext], tolerate_unusable_files=True)

    assert "perfectly good clinical note" in resolved.text
    assert resolved.skipped_files == ["virus.exe"]


# ---------------------------------------------------------------------------
# Job-scoped upload limits (Finding A -- parameterized limits)
# ---------------------------------------------------------------------------

def test_resolve_uploaded_files_respects_custom_max_file_count():
    uploads = [_FakeUpload(f"f{i}.txt", b"a" * 30) for i in range(3)]
    with pytest.raises(ValueError, match="at most 2 files"):
        _resolve(uploads, max_file_count=2)


def test_resolve_uploaded_files_has_no_per_file_size_cap():
    """Explicit product decision: no per-file size limit, only an aggregate
    one -- a single file well under the aggregate cap must succeed no matter
    how large it is relative to any other file."""
    big = _FakeUpload("big.txt", b"a" * 2000)
    resolved, _ = _resolve([big], max_aggregate_bytes=10 * 1024 * 1024)
    assert len(resolved.text) > 0


def test_resolve_uploaded_files_custom_aggregate_limit_still_enforced():
    big = _FakeUpload("big.txt", b"a" * (2 * 1024 * 1024))
    with pytest.raises(ValueError, match="too large"):
        _resolve([big], max_aggregate_bytes=1024 * 1024)


# ---------------------------------------------------------------------------
# Corrupt/unstorable file handling (Finding 5 / 6)
# ---------------------------------------------------------------------------

def test_extract_text_from_bytes_corrupt_pdf_raises_file_parse_failed():
    with pytest.raises(SimplifyError) as exc_info:
        extract_text_from_bytes(b"not a real pdf, just garbage bytes", "notes.pdf")
    assert exc_info.value.error_code == ErrorCode.FILE_PARSE_FAILED


def test_extract_text_from_bytes_empty_pdf_raises_file_parse_failed():
    with pytest.raises(SimplifyError) as exc_info:
        extract_text_from_bytes(b"", "empty.pdf")
    assert exc_info.value.error_code == ErrorCode.FILE_PARSE_FAILED


def test_extract_text_from_bytes_corrupt_docx_raises_file_parse_failed():
    with pytest.raises(SimplifyError) as exc_info:
        extract_text_from_bytes(b"not a real docx, just garbage bytes", "notes.docx")
    assert exc_info.value.error_code == ErrorCode.FILE_PARSE_FAILED


@patch(
    "services.care_plan_input.extract_text_from_bytes",
    return_value="hello \ud800 world -- padding so this clears MIN_MEANINGFUL_CONTENT_CHARS",
)
def test_resolve_uploaded_files_rejects_extracted_text_containing_lone_surrogate(mock_extract):
    """PDF/OCR extraction output can contain a lone surrogate just like pasted
    JSON text (Finding 5) -- resolve_uploaded_files must reject it at the
    per-file boundary regardless of source format, not just for pasted text."""
    fake_upload = _FakeUpload("notes.pdf", b"irrelevant -- extract_text_from_bytes is mocked")
    with pytest.raises(ValueError, match="cannot be saved"):
        _resolve([fake_upload])
