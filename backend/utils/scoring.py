"""
scoring.py — Patient Accessibility Score engine.

Computes a composite 0–100 readability score approximating validated health
literacy tools (PEMAT, SMOG, Flesch-Kincaid, Dale-Chall) using only
automatable signals — no LLM required.

Usage:
    from utils.scoring import score_text
    result = score_text("The patient was diagnosed with hypertension...")
"""

import logging
import re
import textstat

logger = logging.getLogger(__name__)

# ── Optional spaCy for better passive-voice detection ─────────────────────────
try:
    import spacy as _spacy
    _nlp = _spacy.load("en_core_sci_sm")
    _SPACY_AVAILABLE = True
except Exception:
    _SPACY_AVAILABLE = False

# ── Regex patterns ─────────────────────────────────────────────────────────────

PASSIVE_RE = re.compile(
    r'\b(?:was|were|is|are|been|being|am|be)\s+\w+(?:ed|en)\b', re.IGNORECASE
)

VAGUE_RE = re.compile(
    r'\b(?:some|few|many|several|often|occasionally|sometimes|frequently|'
    r'a\s+lot|plenty|numerous|various|certain)\b', re.IGNORECASE
)

FRACTION_RE = re.compile(r'\b\d+/\d+\b')

YOU_RE = re.compile(r'\b(?:you|your|yours)\b', re.IGNORECASE)

# Imperative: sentence starting with a base-form verb (heuristic)
IMPERATIVE_RE = re.compile(
    r'(?:^|(?<=[.!?])\s+)'
    r'(?:Take|Call|Ask|Tell|Bring|Follow|Stop|Start|Avoid|Check|Monitor|'
    r'Schedule|Come|Go|Use|Apply|Keep|Make|Try|Drink|Eat|Rest|Limit|'
    r'Watch|Contact|Return|Seek|Visit|Get|Do|Show|Give|Read|Fill|'
    r'Continue|Discontinue|Wash|Clean|Wear)\b',
    re.MULTILINE,
)

BULLET_RE = re.compile(r'^\s*(?:[-•*]|\d+[.)]\s)', re.MULTILINE)

# ── Normalization helpers ──────────────────────────────────────────────────────

def _grade_to_score(grade: float) -> int:
    """grade 4 → 100, grade 16 → 0, linear, clamped."""
    return max(0, min(100, round((16 - grade) / 12 * 100)))


def _ratio_to_score(ratio: float, worst: float) -> int:
    """0 ratio → 100, worst ratio → 0, linear, clamped."""
    if worst <= 0:
        return 100
    return max(0, min(100, round((1 - ratio / worst) * 100)))


def _count_to_score(count: int, worst: int) -> int:
    """0 count → 100, worst count → 0, linear, clamped."""
    if worst <= 0:
        return 100
    return max(0, min(100, round((1 - count / worst) * 100)))


def _words_per_sentence_to_score(wps: float) -> int:
    """≤10 words/sentence → 100, ≥30 → 0, linear, clamped."""
    return max(0, min(100, round((30 - wps) / 20 * 100)))


def _words_per_para_to_score(wpp: float) -> int:
    """≤30 words/para → 100, ≥120 → 0, linear, clamped."""
    return max(0, min(100, round((120 - wpp) / 90 * 100)))


# ── Sub-scorers ───────────────────────────────────────────────────────────────

def _score_grade_level(text: str) -> tuple[int, float]:
    """Consensus of SMOG + FK Grade + Dale-Chall; returns (score 0-100, grade)."""
    sentence_count = textstat.sentence_count(text)

    fk = textstat.flesch_kincaid_grade(text)
    dc = textstat.dale_chall_readability_score(text)
    # Dale-Chall returns a score; convert to approximate grade
    # DC score ≥ 9.0 → grade 16+, 7.0-8.9 → ~11-12, 5.0-6.9 → ~7-8, <5 → ~4
    dc_grade_map = [(9.0, 16), (8.0, 13), (7.0, 11), (6.0, 8), (5.0, 6), (0.0, 4)]
    dc_grade = next(g for threshold, g in dc_grade_map if dc >= threshold)

    if sentence_count >= 30:
        smog = textstat.smog_index(text)
        grade = (fk + dc_grade + smog) / 3
    else:
        grade = (fk + dc_grade) / 2

    grade = max(0.0, grade)
    return _grade_to_score(grade), round(grade, 1)


def _score_jargon_density(text: str) -> tuple[int, float]:
    """difficult_words / lexicon_count; returns (score, proportion)."""
    lexicon = textstat.lexicon_count(text, removepunct=True)
    if lexicon == 0:
        return 100, 0.0
    difficult = textstat.difficult_words(text)
    ratio = difficult / lexicon
    return _ratio_to_score(ratio, worst=0.40), round(ratio, 3)


def _score_sentence_complexity(text: str) -> tuple[int, float]:
    """Average words per sentence; returns (score, wps)."""
    sentences = textstat.sentence_count(text)
    words = textstat.lexicon_count(text, removepunct=True)
    if sentences == 0:
        return 100, 0.0
    wps = words / sentences
    return _words_per_sentence_to_score(wps), round(wps, 1)


def _score_passive_voice(text: str) -> tuple[int, float]:
    """Passive construction ratio; returns (score, ratio)."""
    sentences = textstat.sentence_count(text)
    if sentences == 0:
        return 100, 0.0

    if _SPACY_AVAILABLE:
        doc = _nlp(text[:50000])  # cap to avoid OOM on huge docs
        passive_count = sum(
            1 for token in doc
            if token.dep_ in ("nsubjpass", "auxpass")
        )
        # Count distinct passive clauses (each nsubjpass = one passive sentence)
        passive_sents = passive_count
    else:
        passive_sents = len(PASSIVE_RE.findall(text))

    ratio = min(passive_sents / sentences, 1.0)
    return _ratio_to_score(ratio, worst=0.50), round(ratio, 3)


def _score_actionability(text: str) -> tuple[int, float]:
    """you/your rate + imperative sentences + bullet presence; returns (score, you-rate)."""
    words = textstat.lexicon_count(text, removepunct=True)
    if words == 0:
        return 0, 0.0

    you_count = len(YOU_RE.findall(text))
    you_rate = you_count / words

    imperative_count = len(IMPERATIVE_RE.findall(text))
    sentences = max(textstat.sentence_count(text), 1)
    imperative_rate = imperative_count / sentences

    has_bullets = 1 if BULLET_RE.search(text) else 0

    # Composite: weight you_rate (40%), imperative_rate (40%), bullets (20%)
    # Normalize each component to 0-1 first
    you_norm = min(you_rate / 0.10, 1.0)        # 10%+ you-rate → max
    imp_norm = min(imperative_rate / 0.20, 1.0) # 20%+ imperative → max
    bullet_norm = float(has_bullets)

    composite = (you_norm * 0.4 + imp_norm * 0.4 + bullet_norm * 0.2)
    score = round(composite * 100)
    return min(score, 100), round(you_rate, 4)


def _score_numeracy_clarity(text: str) -> tuple[int, float]:
    """Vague quantifier count + raw fractions; returns (score, vague count)."""
    vague_count = len(VAGUE_RE.findall(text))
    fraction_count = len(FRACTION_RE.findall(text))
    total = vague_count + fraction_count
    # worst = 20 occurrences → 0
    return _count_to_score(total, worst=20), float(total)


def _score_structural_clarity(text: str) -> tuple[int, float]:
    """Average words per paragraph + bullet presence; returns (score, words/para)."""
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    para_word_counts = [
        textstat.lexicon_count(p, removepunct=True) for p in paragraphs
    ]
    avg_wpp = sum(para_word_counts) / len(para_word_counts)

    wpp_score = _words_per_para_to_score(avg_wpp)

    # Bonus: structured text (bullets/numbers) gets +15 points, capped at 100
    has_structure = bool(BULLET_RE.search(text))
    final_score = min(wpp_score + (15 if has_structure else 0), 100)
    return final_score, round(avg_wpp, 1)


# ── Weights ───────────────────────────────────────────────────────────────────

WEIGHTS = {
    "grade_level":         0.25,
    "jargon_density":      0.20,
    "sentence_complexity": 0.15,
    "passive_voice":       0.10,
    "actionability":       0.10,
    "numeracy_clarity":    0.10,
    "structural_clarity":  0.10,
}

RESEARCH_BASIS = {
    "grade_level": (
        "SMOG (McLaughlin 1969; designed for health materials), "
        "Flesch-Kincaid (1975), Dale-Chall (1948/1995)"
    ),
    "jargon_density": (
        "Dale-Chall familiar word list; PEMAT item 3 (AHRQ 2013)"
    ),
    "sentence_complexity": (
        "PEMAT item 8; AHRQ Health Literacy Universal Precautions Toolkit (3rd ed.)"
    ),
    "passive_voice": (
        "PEMAT item 14; AHRQ active-voice guideline"
    ),
    "actionability": (
        "PEMAT actionability subscale items 27-33 (AHRQ 2013); "
        "CDC Clear Communication Index"
    ),
    "numeracy_clarity": (
        "PEMAT items 21-22; POC spec Step 3 (specificity and numeracy)"
    ),
    "structural_clarity": (
        "SAM (Doak et al. 1996) layout/typography domain; PEMAT items 9-12"
    ),
}


def _label(composite: int) -> str:
    if composite >= 70:
        return "Patient-friendly"
    if composite >= 40:
        return "Moderate"
    return "Hard to read"


# ── Public API ────────────────────────────────────────────────────────────────

def score_text(text: str) -> dict | None:
    """
    Compute a Patient Accessibility Score for the given text.

    Returns None for empty text.
    Returns a dict with composite score, per-dimension breakdown, and metadata.
    Sets low_confidence=True when the sample is too small for reliable scoring.
    """
    if not text or not text.strip():
        return None

    word_count = textstat.lexicon_count(text, removepunct=True)
    sentence_count = textstat.sentence_count(text)

    low_confidence = word_count < 30 or sentence_count < 3

    # ── Compute sub-scores ────────────────────────────────────────────────────
    gl_score, gl_raw    = _score_grade_level(text)
    jd_score, jd_raw    = _score_jargon_density(text)
    sc_score, sc_raw    = _score_sentence_complexity(text)
    pv_score, pv_raw    = _score_passive_voice(text)
    ac_score, ac_raw    = _score_actionability(text)
    nc_score, nc_raw    = _score_numeracy_clarity(text)
    str_score, str_raw  = _score_structural_clarity(text)

    dimensions = {
        "grade_level":         {"score": gl_score,  "raw": gl_raw,  "label": "Grade Level",     "unit": "grade"},
        "jargon_density":      {"score": jd_score,  "raw": jd_raw,  "label": "Jargon Density",  "unit": "proportion"},
        "sentence_complexity": {"score": sc_score,  "raw": sc_raw,  "label": "Sentence Length", "unit": "words/sentence"},
        "passive_voice":       {"score": pv_score,  "raw": pv_raw,  "label": "Active Voice",    "unit": "passive ratio"},
        "actionability":       {"score": ac_score,  "raw": ac_raw,  "label": "Actionability",   "unit": "you-rate"},
        "numeracy_clarity":    {"score": nc_score,  "raw": nc_raw,  "label": "Numeric Clarity", "unit": "vague count"},
        "structural_clarity":  {"score": str_score, "raw": str_raw, "label": "Structure",       "unit": "words/paragraph"},
    }

    composite = round(sum(
        dimensions[dim]["score"] * WEIGHTS[dim]
        for dim in WEIGHTS
    ))

    result: dict = {
        "composite":      composite,
        "grade_estimate": gl_raw,
        "label":          _label(composite),
        "word_count":     word_count,
        "dimensions":     dimensions,
        "research_basis": RESEARCH_BASIS,
    }
    if low_confidence:
        result["low_confidence"] = True

    return result


def score_text_safe(text: str, label: str) -> dict | None:
    """Call score_text; return None and log on any failure."""
    try:
        return score_text(text)
    except Exception:
        logger.exception("scoring: %s-score failed", label)
        return None
