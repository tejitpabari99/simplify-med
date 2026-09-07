"""utils/misc.py — small, single-purpose, side-effect-light helpers that don't
share a cohesive domain (merged from output_helpers.py, html.py, env.py)."""

import logging
import time

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output naming
# ---------------------------------------------------------------------------

def derive_output_name(
    care_plan_data: dict,
    source_filename: str = "",
    group_fallback: str = "",
) -> str:
    """Derive a human-readable output name from care plan data.

    Priority (each result capped at 60 chars):
    1. reason_for_visit[0].reason (title-cased)
    2. diagnosis.main_conclusion first sentence
    3. source_filename stem (if not '' and not 'text_input')
    4. group_fallback (e.g. '{group} {input_id}' for batch)
    5. 'Appointment'
    """
    try:
        rfv = care_plan_data.get("reason_for_visit")
        if rfv and isinstance(rfv, list):
            reason = (rfv[0].get("reason") or "").strip()
            if reason:
                return reason.title()[:60]
        diagnosis = care_plan_data.get("diagnosis") or {}
        main = (diagnosis.get("main_conclusion") or "").strip()
        if main:
            first_sentence = main.split(".")[0].strip()
            if first_sentence:
                return first_sentence[:60]
    except Exception:
        pass
    filename = source_filename or ""
    if filename and filename != "text_input":
        stem = filename.split(",")[0].strip()
        if "." in stem:
            stem = stem.rsplit(".", 1)[0]
        stem = stem.replace("_", " ").replace("-", " ").strip()
        if stem:
            return stem.title()[:60]
    if group_fallback:
        return group_fallback.title()[:60]
    return "Appointment"


# ---------------------------------------------------------------------------
# HTML text extraction
# ---------------------------------------------------------------------------

def extract_text_from_html(html_content: bytes) -> str:
    """Extract plain text from HTML bytes.

    Strategy:
    1. Parse with BeautifulSoup using stdlib html.parser (no lxml needed).
    2. Decompose all <script> and <style> tags and their contents.
    3. Target the <body> element if present; fall back to the full document.
    4. Call .get_text(separator="\\n", strip=True) to produce readable text.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise RuntimeError(
            "beautifulsoup4 is not installed. Add 'beautifulsoup4' to requirements.txt."
        ) from exc

    soup = BeautifulSoup(html_content, "html.parser")

    # Remove non-content tags entirely (including their inner text).
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()

    # Unwrap inline formatting tags so their text stays with the surrounding sentence.
    # Without this, <p>Take <b>2</b> pills daily</p> extracts as "Take\n2\npills\ndaily"
    # because get_text adds separator between every text node.
    _INLINE_TAGS = [
        "a", "abbr", "b", "cite", "code", "em", "i", "kbd", "mark",
        "q", "s", "small", "span", "strong", "sub", "sup", "u",
    ]
    for tag in list(soup.find_all(_INLINE_TAGS)):
        tag.unwrap()
    # Merge adjacent NavigableString nodes created by unwrap() so that
    # get_text() treats them as one unit rather than inserting separators.
    soup.smooth()

    # Prefer the <body> element; fall back to the full document.
    target = soup.body if soup.body else soup

    text = target.get_text(separator="\n", strip=True)
    logger.info("html_extract: %d chars extracted", len(text))
    return text


# ---------------------------------------------------------------------------
# String formatting (used by services/care_plan_input.py)
# ---------------------------------------------------------------------------

def source_separator(filename: str) -> str:
    return f"\n\n--- Source: {filename} ---\n"


def text_artifact_filename(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return f"{stem}.txt"


# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------

def monotonic_ms() -> float:
    """Return current time in milliseconds (monotonic clock). Use for measuring elapsed durations."""
    return time.monotonic() * 1000
