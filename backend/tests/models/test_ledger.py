"""Tests for the ledger models: Unit, Fact, FactCategory, quote_for."""

import pytest
from pydantic import ValidationError

from models.ledger import Fact, Unit, quote_for


def _unit(**overrides) -> Unit:
    fields = dict(id=1, file="note.pdf", page=1, line=1, text="hello world")
    fields.update(overrides)
    return Unit(**fields)


def _fact(**overrides) -> Fact:
    fields = dict(
        id=1,
        category="medications",
        unit_id=1,
        char_start=0,
        char_end=5,
        text="hello",
    )
    fields.update(overrides)
    return Fact(**fields)


def test_unit_round_trips_through_dict():
    unit = _unit()

    assert Unit.from_dict(unit.to_dict()) == unit


def test_fact_round_trips_through_dict():
    fact = _fact()

    assert Fact.from_dict(fact.to_dict()) == fact


def test_fact_rejects_quote_key():
    with pytest.raises(ValidationError):
        Fact(
            id=1,
            category="medications",
            unit_id=1,
            char_start=0,
            char_end=1,
            text="x",
            quote="y",
        )


def test_fact_rejects_invalid_category():
    with pytest.raises(ValidationError):
        _fact(category="not_a_category")


@pytest.mark.parametrize(
    "missing_field",
    ["id", "category", "unit_id", "char_start", "char_end", "text"],
)
def test_fact_requires_all_fields(missing_field):
    fields = dict(
        id=1,
        category="medications",
        unit_id=1,
        char_start=0,
        char_end=5,
        text="hello",
    )
    del fields[missing_field]

    with pytest.raises(ValidationError):
        Fact(**fields)


def test_fact_has_no_quote_attribute():
    fact = _fact()

    assert not hasattr(fact, "quote")


def test_quote_for_returns_unit_text_slice():
    unit = Unit(
        id=1,
        file="f.pdf",
        page=1,
        line=1,
        text="Continue metoprolol 25 mg twice daily",
    )
    start = unit.text.index("metoprolol 25 mg")
    end = start + len("metoprolol 25 mg")
    fact = Fact(
        id=1,
        category="medications",
        unit_id=unit.id,
        char_start=start,
        char_end=end,
        text="Continue metoprolol 25 mg twice daily",
    )

    assert quote_for(fact, {unit.id: unit}) == "metoprolol 25 mg"


def test_quote_for_raises_key_error_on_unknown_unit_id():
    fact = _fact(unit_id=99)

    with pytest.raises(KeyError):
        quote_for(fact, {1: _unit()})
