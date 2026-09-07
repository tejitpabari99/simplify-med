"""Utilities for PDF text extraction and merging."""

from __future__ import annotations

import io
import logging
import textwrap

import PyPDF2
from pypdf import PdfReader, PdfWriter

import pillow_heif
pillow_heif.register_heif_opener()

from utils.constants import Constants

logger = logging.getLogger(__name__)


def extract_text_from_pdf(pdf_content: bytes) -> str:
    reader = PyPDF2.PdfReader(io.BytesIO(pdf_content))
    text_parts: list[str] = []
    for page_num, page in enumerate(reader.pages):
        page_text = page.extract_text()
        if page_text:
            text_parts.append(page_text.strip())
            logger.debug("pdf_extract: page %d: %d chars", page_num + 1, len(page_text))
    full_text = "\n\n".join(text_parts)
    logger.info("pdf_extract: %d total chars from %d pages", len(full_text), len(reader.pages))
    return full_text


def _txt_to_pdf(file_bytes: bytes, filename: str) -> bytes:
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise RuntimeError("reportlab is not installed") from exc

    text = file_bytes.decode("utf-8", errors="replace")
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    margin = 72
    line_height = 14
    y = height - margin

    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(margin, y, filename)
    y -= line_height * 2
    pdf.setFont("Helvetica", 10)

    for raw_line in text.splitlines() or [""]:
        wrapped_lines = textwrap.wrap(raw_line, width=95) or [""]
        for line in wrapped_lines:
            if y < margin:
                pdf.showPage()
                pdf.setFont("Helvetica", 10)
                y = height - margin
            pdf.drawString(margin, y, line)
            y -= line_height

    pdf.save()
    return buffer.getvalue()


def _image_to_pdf(file_bytes: bytes, filename: str) -> bytes:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    from PIL import Image, ImageOps

    img = Image.open(io.BytesIO(file_bytes))
    img = ImageOps.exif_transpose(img)          # respect phone-camera EXIF rotation
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    buffer = io.BytesIO()
    page_w, page_h = letter
    margin = 36
    max_w, max_h = page_w - 2 * margin, page_h - 2 * margin
    scale = min(max_w / img.width, max_h / img.height, 1.0)
    draw_w, draw_h = img.width * scale, img.height * scale

    pdf = canvas.Canvas(buffer, pagesize=letter)
    x = (page_w - draw_w) / 2
    y = (page_h - draw_h) / 2
    pdf.drawImage(ImageReader(img), x, y, width=draw_w, height=draw_h)
    pdf.save()
    return buffer.getvalue()


def _append_pdf(writer: PdfWriter, file_bytes: bytes, filename: str) -> int:
    reader = PdfReader(io.BytesIO(file_bytes))
    page_count = 0
    for page in reader.pages:
        writer.add_page(page)
        page_count += 1
    if page_count == 0:
        logger.warning("pdf_merge: no pages found in %s", filename)
    return page_count


def merge_pdfs(file_list: list[tuple[bytes, str]]) -> bytes:
    """Merge supported PDF/TXT file bytes into a single PDF."""
    writer = PdfWriter()
    merged_pages = 0

    for file_bytes, filename in file_list:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        try:
            if ext == "pdf":
                merged_pages += _append_pdf(writer, file_bytes, filename)
            elif ext == "txt":
                merged_pages += _append_pdf(writer, _txt_to_pdf(file_bytes, filename), filename)
            elif ext in Constants.Uploads.IMAGE_EXTENSIONS:
                merged_pages += _append_pdf(writer, _image_to_pdf(file_bytes, filename), filename)
            else:
                logger.warning("pdf_merge: skipping unsupported file %s", filename)
        except Exception:
            logger.exception("pdf_merge: failed to merge %s; skipping", filename)

    if merged_pages == 0:
        raise ValueError("No mergeable PDF pages found")

    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()
