"""Extract and normalize scientific concepts from title + abstract.

YAKE (Yet Another Keyword Extractor) is unsupervised and deterministic, so the same
text always yields the same concepts — important for reproducibility and for freezing
a vocabulary at a temporal cut. Normalization is deliberately conservative: it lower-
cases, trims punctuation, collapses whitespace and singularizes a trailing plural,
but does NOT merge different multiword terms (that would conflate distinct concepts).

A small stop-concept list removes generic phrases ("this paper", "the results") that
YAKE sometimes surfaces. KeyBERT is provided separately as an optional comparison.
"""

from __future__ import annotations

import re
from functools import lru_cache

_WS = re.compile(r"\s+")
_PUNCT_EDGE = re.compile(r"^[^\w]+|[^\w]+$")
_NONWORD = re.compile(r"[^\w\s-]")

# Generic phrases that are not scientific concepts.
_STOP_CONCEPTS = {
    "paper", "study", "results", "result", "method", "methods", "approach",
    "proposed method", "this paper", "the results", "the paper", "experimental results",
    "present paper", "new method", "data", "analysis", "model", "models", "problem",
    "research", "work", "based", "using", "used", "show", "shown", "propose", "proposed",
}


# Singular scientific terms that end in 's' (or 'ies') and must NOT be singularized.
_UNINFLECTED = {
    "series", "species", "bias", "lens", "gas", "news", "means", "process",
    "status", "basis", "axis", "analysis", "synthesis", "hypothesis", "thesis",
    "diagnosis", "emphasis", "apparatus", "consensus", "corpus", "nucleus", "radius",
}
def _singularize(token: str) -> str:
    """Conservative plural -> singular.

    Preserves scientific terms whose 's' is not a plural (physics, analysis,
    kinetics, series, ...) via a suffix guard and an exception list, so it never
    produces forms like 'physic', 'analysi' or 'sery'. Only clear regular plurals
    are reduced ('networks'->'network', 'categories'->'category').
    """
    if len(token) <= 4 or token in _UNINFLECTED:
        return token
    for suf in ("ss", "us", "is", "sis", "ics", "ous"):
        if token.endswith(suf):
            return token
    if token.endswith("ies"):
        return token[:-3] + "y"      # categories -> category (series/species excepted above)
    if token.endswith("s"):
        return token[:-1]            # networks -> network
    return token


def normalize_concept(concept: str) -> str | None:
    """Normalize a concept string; return None if it reduces to nothing/generic."""
    if not concept:
        return None
    c = concept.lower().strip()
    c = _NONWORD.sub(" ", c)          # drop punctuation except hyphen
    c = _WS.sub(" ", c).strip()
    c = _PUNCT_EDGE.sub("", c)
    if not c:
        return None
    tokens = [_singularize(t) for t in c.split()]
    # Drop leading articles so "the results" -> "result" is caught as generic.
    while tokens and tokens[0] in ("the", "a", "an"):
        tokens = tokens[1:]
    c = " ".join(tokens).strip()
    if not c or c in _STOP_CONCEPTS:
        return None
    if len(c) < 3 or c.isdigit():
        return None
    return c


@lru_cache(maxsize=8)
def _yake_extractor(top: int, ngram: int, lang: str):
    import yake

    return yake.KeywordExtractor(lan=lang, n=ngram, top=top, dedupLim=0.9)


def extract_yake(text: str, *, top_k: int = 15, ngram: int = 3, lang: str = "en") -> list[str]:
    """Extract up to ``top_k`` keyphrases from text with YAKE (lower score = better)."""
    if not text or not text.strip():
        return []
    kw = _yake_extractor(top_k, ngram, lang)
    return [phrase for phrase, _score in kw.extract_keywords(text)]


def extract_document_concepts(
    title: str | None,
    abstract: str | None,
    *,
    top_k: int = 15,
    ngram: int = 3,
) -> list[str]:
    """Extract normalized, de-duplicated concepts from a document's title+abstract.

    Title and abstract are concatenated (title first) so title terms are seen; the
    returned list preserves first-seen order.
    """
    text = " . ".join(t for t in (title, abstract) if t)
    raw = extract_yake(text, top_k=top_k, ngram=ngram)
    seen: set[str] = set()
    out: list[str] = []
    for phrase in raw:
        norm = normalize_concept(phrase)
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out
