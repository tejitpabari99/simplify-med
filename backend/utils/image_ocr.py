"""utils/image_ocr.py — image → clinical text extraction via Gemini vision (Vertex AI)."""

import io

import PIL.Image

from utils.constants import Constants
from utils.llm import LLMClient
from errors import ErrorCode, SimplifyError

_NO_TEXT_SENTINEL = "NO_TEXT_FOUND"
_MAX_LONG_EDGE_PX = 2048

IMAGE_EXT_TO_MIME: dict[str, str] = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "heic": "image/heic",
}


def _maybe_downscale(image_bytes: bytes, ext: str) -> bytes:
    """Resize an image to a max long-edge dimension before sending to Vertex.
    Best-effort: on any decode error, returns the original bytes unchanged."""
    try:
        image = PIL.Image.open(io.BytesIO(image_bytes))
        if max(image.size) <= _MAX_LONG_EDGE_PX:
            return image_bytes
        image.thumbnail((_MAX_LONG_EDGE_PX, _MAX_LONG_EDGE_PX))
        buf = io.BytesIO()
        image.save(buf, format=image.format or "JPEG")
        return buf.getvalue()
    except Exception:
        return image_bytes


def extract_text_from_image(image_bytes: bytes, ext: str) -> str:
    """Extract clinical text from image bytes via Gemini vision on Vertex AI.

    `ext` is the already-lowercased file extension (as produced by
    care_plan_input._get_extension); mapped to a MIME type here so the
    dispatcher in care_plan_input.py stays format-agnostic.
    """
    mime_type = IMAGE_EXT_TO_MIME.get(ext)
    if mime_type is None:
        raise SimplifyError(ErrorCode.UNSUPPORTED_FILE_TYPE, detail=f"extension: {ext}")

    # Validate the bytes actually decode as an image before spending a Vertex
    # AI call on them. Without this, corrupt/zero-byte/garbage image bytes
    # were silently passed through by _maybe_downscale (which swallows decode
    # errors as "best effort, fall back to original bytes" -- appropriate for
    # its own resize-only job, not for detecting a genuinely unreadable file)
    # straight into generate_text_from_image, producing either a confusing
    # Vertex API error or unreliable model behavior instead of a clean,
    # actionable 400 (edge-case review Finding 6 -- verified for PyPDF2;
    # image bytes have the same class of gap). Image.verify() invalidates
    # the object for further use, which is fine: _maybe_downscale below opens
    # its own fresh Image from the same bytes.
    try:
        PIL.Image.open(io.BytesIO(image_bytes)).verify()
    except Exception as exc:
        raise SimplifyError(
            ErrorCode.FILE_PARSE_FAILED,
            detail=f"Image could not be decoded -- it may be corrupted or not actually "
                   f"a {ext.upper()} file ({type(exc).__name__}).",
            original=exc,
        ) from exc

    image_bytes = _maybe_downscale(image_bytes, ext)

    client = LLMClient()
    # Long-form budget: this call transcribes ALL visible text from a full
    # document page image verbatim (see IMAGE_OCR_PROMPT) -- a dense scanned
    # page can produce output well past the default 8192-token cap, so use the
    # same long-form budget as the pipeline's other full-document text steps.
    text = client.generate_text_from_image(
        image_bytes=image_bytes,
        mime_type=mime_type,
        prompt=Constants.Llm.IMAGE_OCR_PROMPT,
        temperature=Constants.Llm.TEMPERATURE_TEXT,
        max_tokens=Constants.Llm.MAX_TOKENS_LONG_FORM,
    )
    if text.strip().upper() == _NO_TEXT_SENTINEL:
        raise SimplifyError(
            ErrorCode.EMPTY_DOCUMENT,
            detail="Image contained no readable text (model returned NO_TEXT_FOUND).",
        )
    return text
