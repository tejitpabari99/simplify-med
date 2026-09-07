"""Shared text normalization helpers for deterministic term matching."""

import re
import unicodedata


def normalize_text(text: str) -> str:
    """Lowercase, strip accents, and collapse whitespace."""
    # NFKD splits accented characters into base + combining mark so we can
    # strip non-ASCII marks deterministically.
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = nfkd.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.lower().split())

def contains_normalized_term(normalized_text: str, normalized_term: str) -> bool:
    """Return true when a normalized term appears with word boundaries."""
    pattern = rf"(?<!\w){re.escape(normalized_term)}(?!\w)"
    return re.search(pattern, normalized_text) is not None


def term_aliases(term: str) -> list[str]:
    """Split source entries like 'agitate, agitation' into lookup aliases."""
    aliases: list[str] = []
    seen: set[str] = set()

    def _add(alias: str) -> None:
        alias = alias.strip().strip(":")
        if alias and alias not in seen:
            seen.add(alias)
            aliases.append(alias)

    # First pass: comma-separated aliases from the source term field.
    for alias in re.split(r"\s*,\s*", term):
        _add(alias)
    
        parenthetical = re.search(r"\(([^)]+)\)", alias)
        if parenthetical:
            # "stroke (CVA)" -> "stroke", "stroke CVA", and "CVA".
            without_parenthetical = re.sub(r"\s*\([^)]+\)", "", alias).strip()
            parenthetical_text = parenthetical.group(1).strip()
            _add(without_parenthetical)
            if len(parenthetical_text) == 1 and parenthetical_text.isalpha():
                _add(f"{without_parenthetical}{parenthetical_text}")
            else:
                _add(f"{without_parenthetical} {parenthetical_text}")
                for inner_alias in re.split(r"\s+or\s+|\s*/\s*", parenthetical_text):
                    if inner_alias.isupper() and len(inner_alias) > 1:
                        _add(inner_alias)

        if "/" in alias:
            # "pain/discomfort" and "chest pain/discomfort" produce both options.
            prefix, alternatives = alias.rsplit(" ", 1) if " " in alias else ("", alias)
            for alternative in alternatives.split("/"):
                _add(f"{prefix} {alternative}" if prefix else alternative)

    return aliases or [term]


def _pluralize_word(word: str) -> set[str]:
    if word.endswith("y") and len(word) > 1 and word[-2].lower() not in "aeiou":
        return {f"{word[:-1]}ies"}
    if word.endswith(("s", "x", "z", "ch", "sh")):
        return {f"{word}es"}
    return {f"{word}s"}


def _is_probable_verb_base(word: str) -> bool:
    noun_suffixes = (
        "ed",
        "tion",
        "sion",
        "ment",
        "ness",
        "ity",
        "ence",
        "ance",
        "ism",
        "ics",
        "osis",
        "gram",
        "graph",
        "ile",
        "que",
    )
    return not word.endswith(noun_suffixes)


def _doubles_final_consonant(word: str) -> bool:
    if len(word) < 3 or word[-1].lower() in "wxy":
        return False
    return (
        word[-1].lower() not in "aeiou"
        and word[-2].lower() in "aeiou"
        and word[-3].lower() not in "aeiou"
    )


def _verb_inflections(word: str) -> set[str]:
    if word.endswith("ie"):
        return {f"{word}s", f"{word}d", f"{word[:-2]}ying"}
    if word.endswith("y") and len(word) > 1 and word[-2].lower() not in "aeiou":
        return {f"{word[:-1]}ies", f"{word[:-1]}ied", f"{word}ing"}
    if word.endswith("e"):
        return {f"{word}s", f"{word}d", f"{word[:-1]}ing"}
    if _doubles_final_consonant(word):
        return {f"{word}s", f"{word}{word[-1]}ed", f"{word}{word[-1]}ing"}
    return {f"{word}s", f"{word}ed", f"{word}ing"}


def inflected_aliases(term: str) -> list[str]:
    """Generate conservative English variants for single-word dictionary terms."""
    aliases = term_aliases(term)
    for alias in list(aliases):
        # Only inflect simple alphabetic, non-acronym aliases to avoid noisy
        # expansions that can produce false positives.
        if not re.fullmatch(r"[A-Za-z]+", alias):
            continue
        if alias.isupper():
            continue
        if alias.endswith(("ed", "ile", "noun")):
            continue
        if alias.endswith("s") and not alias.endswith("ss"):
            continue

        # Noun pluralization plus optional verb forms when alias looks verbal.
        variants = _pluralize_word(alias)
        if _is_probable_verb_base(alias):
            variants.update(_verb_inflections(alias))
        for variant in variants:
            if variant not in aliases:
                aliases.append(variant)
    return aliases
