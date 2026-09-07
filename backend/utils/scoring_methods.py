import textstat
from utils.scoring import _grade_to_score
from utils.constants import Constants


def score_smog(text: str) -> dict:
    sentence_count = textstat.sentence_count(text)
    if sentence_count < 30:
        return {"grade": 0.0, "insufficient_sample": True, "score": 0}
    grade = textstat.smog_index(text)
    return {"grade": round(grade, 1), "insufficient_sample": False, "score": _grade_to_score(grade)}


def score_flesch_kincaid(text: str) -> dict:
    reading_ease = textstat.flesch_reading_ease(text)
    grade_level = textstat.flesch_kincaid_grade(text)
    return {
        "reading_ease": round(reading_ease, 1),
        "grade_level": round(grade_level, 1),
        "score": max(0, min(100, round(reading_ease))),
    }


def score_dale_chall(text: str) -> dict:
    raw = textstat.dale_chall_readability_score(text)
    grade_range = _dc_grade_range(raw)
    grade = max(4.0, min(16.0, raw / 9.0 * 12 + 4))
    return {"raw_score": round(raw, 2), "grade_range": grade_range, "score": _grade_to_score(grade)}


def _dc_grade_range(raw: float) -> str:
    if raw >= 9.0: return "College level"
    if raw >= 8.0: return "11th–12th grade"
    if raw >= 7.0: return "9th–10th grade"
    if raw >= 6.0: return "7th–8th grade"
    if raw >= 5.0: return "5th–6th grade"
    return "4th grade or below"


def score_pemat(dimensions: dict) -> dict:
    # Approximation of PEMAT (AHRQ 2013) from automatable dimension scores.
    # Understandability: items 3,8,14,21-22,9-12; Actionability: items 27-33.
    understandability = round((
        dimensions["jargon_density"]["score"] * 0.25 +
        dimensions["sentence_complexity"]["score"] * 0.25 +
        dimensions["passive_voice"]["score"] * 0.20 +
        dimensions["numeracy_clarity"]["score"] * 0.15 +
        dimensions["structural_clarity"]["score"] * 0.15
    ))
    actionability = dimensions["actionability"]["score"]
    combined = round((understandability + actionability) / 2)
    return {"understandability": understandability, "actionability": actionability, "score": combined}


def score_sam(dimensions: dict) -> dict:
    # Approximation of automatable SAM domains (Doak et al. 1996).
    # Content (0-8), literacy demand (0-14), layout/typography (0-6).
    content = round(
        (dimensions["grade_level"]["score"] * 0.5 + dimensions["jargon_density"]["score"] * 0.5) / 100 * 8
    )
    literacy_demand = round(
        (dimensions["grade_level"]["score"] * 0.5 +
         dimensions["sentence_complexity"]["score"] * 0.3 +
         dimensions["passive_voice"]["score"] * 0.2) / 100 * 14
    )
    layout_typography = round(dimensions["structural_clarity"]["score"] / 100 * 6)
    total_possible = 28  # only automatable domains
    total = content + literacy_demand + layout_typography
    score = round(total / total_possible * 100)
    return {"content": content, "literacy_demand": literacy_demand,
            "layout_typography": layout_typography, "score": score}


def score_cdc_cci(dimensions: dict) -> dict:
    # Approximation of CDC Clear Communication Index automatable items.
    main_message = 1 if dimensions["actionability"]["score"] >= 50 else 0
    behavioral = 1 if (
        dimensions["actionability"]["score"] + dimensions["numeracy_clarity"]["score"]
    ) / 2 >= 50 else 0
    numbers = 1 if dimensions["numeracy_clarity"]["score"] >= 50 else 0
    call_to_action = 1 if dimensions["actionability"]["score"] >= 60 else 0
    items_met = main_message + behavioral + numbers + call_to_action
    score = round(items_met / 4 * 100)
    return {
        "main_message": main_message,
        "behavioral_recommendations": behavioral,
        "numbers": numbers,
        "call_to_action": call_to_action,
        "score": score,
    }


def compute_method_scores(text: str, dimensions: dict) -> dict:
    """Compute all six method-level scores for a given text + precomputed dimension dict."""
    
    return {
        Constants.Grading.GRADING_METHODS.SMOG:           score_smog(text),
        Constants.Grading.GRADING_METHODS.FLESCH_KINCAID: score_flesch_kincaid(text),
        Constants.Grading.GRADING_METHODS.DALE_CHALL:     score_dale_chall(text),
        Constants.Grading.GRADING_METHODS.PEMAT:          score_pemat(dimensions),
        Constants.Grading.GRADING_METHODS.SAM:            score_sam(dimensions),
        Constants.Grading.GRADING_METHODS.CDC_CCI:        score_cdc_cci(dimensions),
    }
