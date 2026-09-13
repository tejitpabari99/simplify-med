"""One-time, re-runnable prune of michigan_medical_dictionary.json against
common_word_stoplist.json. Rerun this whenever the source dictionary is
refreshed from https://medicaldictionary.lib.umich.edu/ -- do not apply the
stoplist at load time (see PRD 07 SS4.2); every prune is a reviewed, committed
diff, never a silent runtime filter.

A record is dropped only if EVERY comma-separated branch of its canonical
`term` is in the stoplist. A term with a parenthetical qualifier
("plaque (in an artery)") is NEVER dropped, regardless of its bare form --
the qualifier itself is evidence the entry captures a specific clinical
sense a bare stoplist word does not (verified: no such record exists in the
current file where the bare, paren-stripped form is also a stoplist word).
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "jargon"

def _branches(term: str) -> list[str]:
    return [p.strip().lower() for p in term.split(",")]

def _normalize_stoplist(stoplist: set[str]) -> set[str]:
    # A stoplist entry may itself be a comma-list ("foot, feet"); split it into
    # bare branches the same way a dictionary term is split, so a record like
    # "foot, feet" can match branch-for-branch against the stoplist instead of
    # only ever comparing against the literal, unsplit stoplist string.
    normalized: set[str] = set()
    for entry in stoplist:
        normalized.update(_branches(entry))
    return normalized

def prune(dictionary: list[dict], stoplist: set[str]) -> tuple[list[dict], list[dict]]:
    normalized_stoplist = _normalize_stoplist(stoplist)
    kept, dropped = [], []
    for record in dictionary:
        term = record["term"]
        if "(" in term:
            kept.append(record)
            continue
        if all(branch in normalized_stoplist for branch in _branches(term)):
            dropped.append(record)
        else:
            kept.append(record)
    return kept, dropped

if __name__ == "__main__":
    dictionary = json.loads((DATA_DIR / "michigan_medical_dictionary.json").read_text())
    stoplist = set(json.loads((DATA_DIR / "common_word_stoplist.json").read_text()))
    kept, dropped = prune(dictionary, stoplist)
    print(f"Dropping {len(dropped)} of {len(dictionary)} records:")
    for record in dropped:
        print(f"  {record['term']!r}: {record['definition'][:70]!r}")
    (DATA_DIR / "michigan_medical_dictionary.json").write_text(
        json.dumps(kept, indent=2) + "\n"
    )
