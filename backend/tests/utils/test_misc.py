"""Tests for utils/misc.py (consolidated from test_env.py, test_output_helpers.py,
test_html.py)."""

from utils.misc import derive_output_name, extract_text_from_html


# ---------------------------------------------------------------------------
# derive_output_name (formerly tests/utils/test_output_helpers.py)
# ---------------------------------------------------------------------------

def test_rfv_reason_title_cased():
    result = derive_output_name({"reason_for_visit": [{"reason": "chest pain"}]})
    assert result == "Chest Pain"


def test_diagnosis_fallback():
    data = {"reason_for_visit": [], "diagnosis": {"main_conclusion": "Hypertension. More details."}}
    result = derive_output_name(data)
    assert result == "Hypertension"


def test_filename_fallback():
    result = derive_output_name({}, source_filename="annual_checkup.pdf")
    assert result == "Annual Checkup"


def test_group_fallback():
    result = derive_output_name({}, group_fallback="sp1 0001")
    assert result == "Sp1 0001"


def test_appointment_fallback():
    result = derive_output_name({})
    assert result == "Appointment"


def test_max_60_chars():
    long_reason = "a" * 100
    result = derive_output_name({"reason_for_visit": [{"reason": long_reason}]})
    assert len(result) == 60


def test_text_input_filename_skipped():
    result = derive_output_name({}, source_filename="text_input")
    assert result == "Appointment"


# ---------------------------------------------------------------------------
# extract_text_from_html (formerly tests/utils/test_html.py)
# ---------------------------------------------------------------------------

def _html(body: str, *, with_body_tag: bool = True) -> bytes:
    if with_body_tag:
        return f"<html><body>{body}</body></html>".encode()
    return f"<html>{body}</html>".encode()


def test_extract_text_returns_visible_text():
    """Basic content in a paragraph is included in output."""
    html = _html("<p>Hello patient</p>")
    result = extract_text_from_html(html)
    assert "Hello patient" in result


def test_extract_text_strips_script_tags():
    """Content inside <script> is NOT included in output."""
    html = _html("<p>Visible</p><script>var secret = 1;</script>")
    result = extract_text_from_html(html)
    assert "secret" not in result
    assert "Visible" in result


def test_extract_text_strips_style_tags():
    """Content inside <style> is NOT included in output."""
    html = _html("<style>body { color: red; }</style><p>Styled text</p>")
    result = extract_text_from_html(html)
    assert "color" not in result
    assert "Styled text" in result


def test_extract_text_without_body_tag():
    """Falls back to full document when no <body> element exists."""
    html = b"<p>No body wrapper</p>"
    result = extract_text_from_html(html)
    assert "No body wrapper" in result


def test_extract_text_returns_string():
    """Return type is always str, even for empty input."""
    result = extract_text_from_html(b"<html></html>")
    assert isinstance(result, str)


def test_extract_text_empty_document_returns_empty_string():
    """An empty or whitespace-only document returns an empty or near-empty string."""
    result = extract_text_from_html(b"<html><body>   </body></html>")
    assert result.strip() == ""


def test_extract_text_multiline_content():
    """Multiple paragraphs produce multi-line output with content preserved."""
    html = _html("<p>Take this medication daily.</p><p>Follow up in 2 weeks.</p>")
    result = extract_text_from_html(html)
    assert "Take this medication daily." in result
    assert "Follow up in 2 weeks." in result


def test_extract_text_preserves_inline_formatting():
    """Inline tags like <b> and <i> do not fragment the surrounding text."""
    html = _html("<p>Take <b>2</b> pills <i>daily</i> with food.</p>")
    result = extract_text_from_html(html)
    # All words should appear on the same line, not fragmented across lines
    assert "Take 2 pills daily with food." in result
