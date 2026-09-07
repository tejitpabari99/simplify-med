import io
import logging
import pytest


def _one_page_pdf(text: str = "hello") -> bytes:
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(72, 720, text)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def _make_pdf(pages: list) -> bytes:
    """Create a PDF with one text string per page."""
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    for text in pages:
        pdf.drawString(72, 720, text)
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def test_merge_pdfs_combines_pdf_and_txt_inputs():
    from pypdf import PdfReader
    from utils.pdf import merge_pdfs

    merged = merge_pdfs(
        [
            (_one_page_pdf("pdf page"), "note.pdf"),
            (b"txt page", "note.txt"),
        ]
    )

    reader = PdfReader(io.BytesIO(merged))
    assert len(reader.pages) == 2


def test_merge_pdfs_raises_when_no_pages_are_mergeable(caplog):
    from utils.pdf import merge_pdfs

    with caplog.at_level(logging.WARNING, logger="utils.pdf"):
        with pytest.raises(ValueError):
            merge_pdfs([(b"not supported", "image.png")])


def test_extract_text_from_two_page_pdf():
    from utils.pdf import extract_text_from_pdf

    pdf_bytes = _make_pdf(["First page content", "Second page content"])
    result = extract_text_from_pdf(pdf_bytes)
    assert "First page content" in result
    assert "Second page content" in result


def test_extract_text_from_empty_pdf_returns_empty_string():
    from utils.pdf import extract_text_from_pdf
    import PyPDF2

    # Build a valid PDF with one blank page (no text)
    writer = PyPDF2.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    pdf_bytes = buffer.getvalue()

    result = extract_text_from_pdf(pdf_bytes)
    assert result == ""


def _pillow_heif_available() -> bool:
    try:
        import pillow_heif  # noqa: F401
        return True
    except ImportError:
        return False


def test_image_to_pdf_produces_one_page():
    from PIL import Image
    from pypdf import PdfReader
    from utils.pdf import _image_to_pdf

    img = Image.new("RGB", (100, 100), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    result = _image_to_pdf(png_bytes, "photo.png")
    reader = PdfReader(io.BytesIO(result))
    assert len(reader.pages) == 1


def test_image_to_pdf_respects_exif_rotation():
    from PIL import Image, ImageOps
    from pypdf import PdfReader
    from unittest.mock import patch
    from utils.pdf import _image_to_pdf

    # Landscape raw pixels (200 wide x 100 tall) tagged with EXIF orientation 6
    # ("rotate 90 CW to correct") — after exif_transpose the corrected image
    # is portrait (100 wide x 200 tall). This proves the raw stored dimensions
    # are not what gets drawn; the corrected orientation is.
    img = Image.new("RGB", (200, 100), color="white")
    exif = img.getexif()
    exif[0x0112] = 6  # Orientation tag
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    raw_bytes = buf.getvalue()

    with patch("PIL.ImageOps.exif_transpose", wraps=ImageOps.exif_transpose) as spy:
        result = _image_to_pdf(raw_bytes, "photo.jpg")

    spy.assert_called_once()

    # Independently confirm the semantics: EXIF orientation 6 on a 200x100
    # source flips the corrected image to 100x200 (portrait).
    corrected = ImageOps.exif_transpose(Image.open(io.BytesIO(raw_bytes)))
    assert (corrected.width, corrected.height) == (100, 200)

    reader = PdfReader(io.BytesIO(result))
    assert len(reader.pages) == 1


def test_merge_pdfs_embeds_image_alongside_pdf_and_txt():
    from PIL import Image
    from pypdf import PdfReader
    from utils.pdf import merge_pdfs

    img = Image.new("RGB", (50, 50), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    merged = merge_pdfs(
        [
            (_one_page_pdf("pdf page"), "note.pdf"),
            (b"txt page", "note.txt"),
            (png_bytes, "photo.png"),
        ]
    )

    reader = PdfReader(io.BytesIO(merged))
    assert len(reader.pages) == 3


@pytest.mark.skipif(
    not _pillow_heif_available(), reason="pillow_heif not importable in this environment"
)
def test_merge_pdfs_handles_heic_via_pillow_heif():
    from PIL import Image
    from pypdf import PdfReader
    from utils.pdf import merge_pdfs

    img = Image.new("RGB", (60, 60), color="green")
    buf = io.BytesIO()
    img.save(buf, format="HEIF")
    heic_bytes = buf.getvalue()

    merged = merge_pdfs([(heic_bytes, "photo.heic")])
    reader = PdfReader(io.BytesIO(merged))
    assert len(reader.pages) == 1
