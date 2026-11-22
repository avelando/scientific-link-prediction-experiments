"""Concept extraction and normalization (project §4.1).

Primary representation is title + abstract (the project's main representation).
YAKE is the primary extractor (lightweight, unsupervised, reproducible); KeyBERT
is an optional comparison. OpenAlex topics are NOT used as concepts — concepts come
from the text.
"""

from slpe.concepts.extract import (
    extract_document_concepts,
    extract_yake,
    normalize_concept,
)

__all__ = ["extract_document_concepts", "extract_yake", "normalize_concept"]
