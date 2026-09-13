"""tests/utils/test_image_ocr.py — Tests for utils/image_ocr.py.

Mocks utils.image_ocr.LLMClient (patch the class, configure
generate_text_from_image on the mock instance) — no real Vertex/network calls.
"""
import io
from unittest.mock import MagicMock, patch

import pytest
import PIL.Image

from utils.constants import Constants
from utils.image_ocr import extract_text_from_image, IMAGE_EXT_TO_MIME, _maybe_downscale
from errors import ErrorCode, SimplifyError


def _valid_png_bytes() -> bytes:
    """A minimal, real, decodable PNG -- needed because extract_text_from_image
    now validates the bytes decode as an image before calling the LLM."""
    img = PIL.Image.new("RGB", (10, 10), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@patch("utils.image_ocr.LLMClient")
def test_extract_text_from_image_returns_model_text(mock_llm_client_cls):
    mock_instance = MagicMock()
    mock_instance.generate_text_from_image.return_value = "Patient note text"
    mock_llm_client_cls.return_value = mock_instance

    result = extract_text_from_image(_valid_png_bytes(), "png")

    assert result == "Patient note text"


@patch("utils.image_ocr.LLMClient")
def test_extract_text_from_image_no_text_sentinel_raises_empty_document(mock_llm_client_cls):
    mock_instance = MagicMock()
    mock_instance.generate_text_from_image.return_value = "NO_TEXT_FOUND"
    mock_llm_client_cls.return_value = mock_instance

    with pytest.raises(SimplifyError) as exc_info:
        extract_text_from_image(_valid_png_bytes(), "png")

    assert exc_info.value.error_code == ErrorCode.EMPTY_DOCUMENT


@patch("utils.image_ocr.LLMClient")
def test_extract_text_from_image_corrupt_bytes_raises_file_parse_failed(mock_llm_client_cls):
    """Regression (Finding 6, image equivalent): corrupt/garbage image bytes
    must raise a clean FILE_PARSE_FAILED before any Vertex AI call, not an
    uncaught downstream error."""
    with pytest.raises(SimplifyError) as exc_info:
        extract_text_from_image(b"this is not a valid image", "png")

    assert exc_info.value.error_code == ErrorCode.FILE_PARSE_FAILED
    mock_llm_client_cls.assert_not_called()


@patch("utils.image_ocr.LLMClient")
def test_extract_text_from_image_unknown_extension_raises_unsupported_file_type(mock_llm_client_cls):
    with pytest.raises(SimplifyError) as exc_info:
        extract_text_from_image(b"bytes", "gif")

    assert exc_info.value.error_code == ErrorCode.UNSUPPORTED_FILE_TYPE
    mock_llm_client_cls.assert_not_called()


def test_image_ext_to_mime_covers_all_image_extensions():
    assert set(IMAGE_EXT_TO_MIME) == Constants.Uploads.IMAGE_EXTENSIONS


@patch("utils.image_ocr._maybe_downscale")
@patch("utils.image_ocr.LLMClient")
def test_extract_text_from_image_downscales_before_sending(mock_llm_client_cls, mock_downscale):
    mock_instance = MagicMock()
    mock_instance.generate_text_from_image.return_value = "some text"
    mock_llm_client_cls.return_value = mock_instance
    mock_downscale.return_value = b"downscaled-bytes"
    original_bytes = _valid_png_bytes()

    result = extract_text_from_image(original_bytes, "png")

    mock_downscale.assert_called_once_with(original_bytes, "png")
    assert mock_instance.generate_text_from_image.call_args.kwargs["image_bytes"] == b"downscaled-bytes"
    assert result == "some text"


def test_maybe_downscale_returns_unchanged_for_small_image():
    import io
    import PIL.Image

    img = PIL.Image.new("RGB", (100, 100), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    original_bytes = buf.getvalue()

    assert _maybe_downscale(original_bytes, "png") == original_bytes


def test_maybe_downscale_returns_original_on_decode_error():
    corrupted = b"this is not a valid image"
    assert _maybe_downscale(corrupted, "png") == corrupted


def test_max_long_edge_is_4096():
    from utils.image_ocr import _MAX_LONG_EDGE_PX
    assert _MAX_LONG_EDGE_PX == 4096


def test_maybe_downscale_leaves_image_between_old_and_new_ceiling_unchanged():
    # a ~3000px-long-edge image: under the new 4096 ceiling, _maybe_downscale
    # must return it unchanged (regression-proof the ceiling actually moved --
    # under the OLD 2048 ceiling this image would have been downscaled)
    img = PIL.Image.new("RGB", (3000, 100), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    original_bytes = buf.getvalue()

    assert _maybe_downscale(original_bytes, "png") == original_bytes


def test_maybe_downscale_still_downscales_image_over_new_ceiling():
    # an image over 4096px long edge is thumbnailed to <= 4096
    img = PIL.Image.new("RGB", (5000, 100), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    original_bytes = buf.getvalue()

    result = _maybe_downscale(original_bytes, "png")

    result_img = PIL.Image.open(io.BytesIO(result))
    assert max(result_img.size) <= 4096
