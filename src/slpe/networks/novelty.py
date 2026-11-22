"""Historical novelty ledger.

A concept pair is a NOVELTY candidate at cut T only if the two concepts never
co-occurred in the full OBSERVED history up to T — not merely absent from the recent
L-year feature window (project §4.1). The ledger accumulates every co-occurred pair
across all documents dated <= T, so an old association is not mistaken for new.

Because the corpus is sampled, "novel" means "no observed co-occurrence in the
sampled historical corpus", NOT globally new in the literature.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from itertools import combinations


class NoveltyLedger:
    """Accumulates co-occurred concept pairs and known concepts up to a cut."""

    def __init__(self) -> None:
        self._pairs: set[frozenset[str]] = set()
        self._concepts: set[str] = set()

    def add_document(self, concepts: Iterable[str]) -> None:
        unique = sorted(set(concepts))
        self._concepts.update(unique)
        for a, b in combinations(unique, 2):
            self._pairs.add(frozenset((a, b)))

    def add_documents(self, doc_concepts: Mapping[str, Iterable[str]]) -> None:
        for concepts in doc_concepts.values():
            self.add_document(concepts)

    def has_cooccurred(self, a: str, b: str) -> bool:
        return frozenset((a, b)) in self._pairs

    def knows(self, concept: str) -> bool:
        return concept in self._concepts

    @property
    def concepts(self) -> set[str]:
        return self._concepts

    @property
    def n_pairs(self) -> int:
        return len(self._pairs)

    def is_candidate(self, a: str, b: str) -> bool:
        """True if both concepts are known and the pair has never co-occurred."""
        return a != b and a in self._concepts and b in self._concepts \
            and frozenset((a, b)) not in self._pairs
