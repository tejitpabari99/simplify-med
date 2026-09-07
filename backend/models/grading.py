from datetime import datetime, timezone
from typing import Literal

from pydantic import Field

from .base import JsonModel
from utils.constants import Constants


GRADING_VERSION = Constants.Schema.GRADING_VERSION


class GradingEntry(JsonModel):
    name: str       # "smog" | "flesch_kincaid" | "dale_chall" | "pemat" | "sam" | "cdc_cci" | "combined"
    target: Literal["before", "after"]
    grade: float    # 0-100 normalized score
    description: str | None = None
    grade_breakdown: dict | None = None
    reasoning: str | None = None


class Grading(JsonModel):
    entries: list[GradingEntry] = Field(default_factory=list)
    enabled: bool = True
    graded_at: str | None = None


def build_grading_with_before_after_score(
    before_score: dict | None, before_text: str | None,
    after_score: dict | None, after_text: str | None,
) -> Grading:
    from utils.scoring_methods import compute_method_scores

    entries = []
    for target, score, text in (
        ("before", before_score, before_text),
        ("after", after_score, after_text),
    ):
        if score is None or text is None:
            continue
        methods = compute_method_scores(text, score["dimensions"])
        for method in Constants.Grading.GRADING_METHODS:
            m = methods[method]
            breakdown = {k: v for k, v in m.items() if k != "score"}
            entries.append(GradingEntry(
                name=method.value.value,
                target=target,
                grade=m["score"],
                grade_breakdown=breakdown,
                reasoning=method.value.description,
            ))
        entries.append(GradingEntry(
            name="combined",
            target=target,
            grade=score["composite"],
            grade_breakdown={
                "grade_estimate": score["grade_estimate"],
                "label":          score["label"],
                "word_count":     score["word_count"],
                "dimensions":     score["dimensions"],
            },
            reasoning=None,
        ))
    return Grading(
        entries=entries,
        enabled=True,
        graded_at=datetime.now(timezone.utc).isoformat(),
    )
