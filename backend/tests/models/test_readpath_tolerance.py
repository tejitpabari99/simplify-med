"""Tests for free read-path tolerance on strict model payloads."""

import json
from pathlib import Path

from models.care_plan.care_plan import CarePlan


FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "care_plan.json"


def test_care_plan_without_raw_validates_for_free_read_tolerance():
    data = json.loads(FIXTURE_PATH.read_text())
    data.pop("raw")

    # No migration or legacy-handling code; this is only free read tolerance.
    model = CarePlan.model_validate(data)

    assert model.raw is None
