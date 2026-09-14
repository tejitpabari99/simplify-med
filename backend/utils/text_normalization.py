"""Shared text normalization helpers for deterministic term matching."""

import re
import unicodedata


def normalize_with_offsets(text: str) -> tuple[str, list[tuple[int, int]]]:
    """Like normalize_text, but also returns, for each character of the
    normalized output, the (start, end) span of raw `text` indices
    (Python slice semantics) it was derived from -- `len(spans) ==
    len(normalized)` always. Used by grounding (PRD 03 §4.3) to recover
    char_start/char_end for a quote already proven verbatim by
    normalize_text-based comparison, when a naive `str.find` on the raw
    strings would miss a whitespace- or case-normalized match.

    Algorithm, in two passes:

    1. Per-character transliteration. For each raw character at index i,
       run it individually through the same transformation normalize_text
       already applies to the whole string -- NFKD decompose, ASCII-encode
       with errors="ignore", lowercase. Unicode's canonical/compatibility
       decomposition is memoryless (a character's decomposition never
       depends on its neighbors), so doing this one character at a time
       yields the same result as doing it to the whole string at once.
       This produces zero or more output characters per raw character
       (zero if the character is dropped entirely, e.g. a symbol with no
       ASCII equivalent; more than one only for the rare compatibility
       decomposition that expands into multiple ASCII characters, e.g. a
       ligature). Every emitted character is tagged with the raw span
       (i, i+1) of the single input character that produced it.

    2. Whitespace collapse, mirroring `" ".join(text.split())`: scan the
       tagged character list and replace each maximal run of
       whitespace-classified characters with a single " ", tagged with the
       span (first run member's start, last run member's end); drop
       leading and trailing whitespace runs entirely (no character
       emitted, matching `str.split()`'s own behavior).

    The result is character-identical to normalize_text(text) by
    construction (both passes implement exactly normalize_text's own
    documented steps -- decompose, ASCII-ignore, lowercase, whitespace
    collapse-and-strip), which is what test_normalize_with_offsets_matches_
    normalize_text (§7.3) checks across a corpus of representative inputs.
    """
    # Pass 1: per-character transliteration, each emitted character tagged
    # with the raw (i, i+1) span of the single input character it came from.
    chars: list[str] = []
    spans: list[tuple[int, int]] = []
    for i, raw_char in enumerate(text):
        nfkd = unicodedata.normalize("NFKD", raw_char)
        ascii_char = nfkd.encode("ascii", "ignore").decode("ascii").lower()
        for out_char in ascii_char:
            chars.append(out_char)
            spans.append((i, i + 1))

    # Pass 2: whitespace collapse, mirroring " ".join(text.split()) -- a
    # maximal interior run of whitespace becomes a single " " tagged with
    # the run's own start/end; leading/trailing runs are dropped entirely.
    normalized_chars: list[str] = []
    normalized_spans: list[tuple[int, int]] = []
    total = len(chars)
    i = 0
    while i < total:
        if chars[i].isspace():
            run_start = spans[i][0]
            run_end = spans[i][1]
            j = i
            while j < total and chars[j].isspace():
                run_end = spans[j][1]
                j += 1
            if normalized_chars and j < total:
                # Interior run: neither leading (something already emitted)
                # nor trailing (more non-whitespace content follows).
                normalized_chars.append(" ")
                normalized_spans.append((run_start, run_end))
            i = j
        else:
            normalized_chars.append(chars[i])
            normalized_spans.append(spans[i])
            i += 1

    return "".join(normalized_chars), normalized_spans


def normalize_text(text: str) -> str:
    """Lowercase, strip accents, and collapse whitespace."""
    return normalize_with_offsets(text)[0]


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
