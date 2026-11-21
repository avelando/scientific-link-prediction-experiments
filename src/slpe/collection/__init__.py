"""Stage 2 — historical corpus collection, deduplication and preparation.

Subpackage layout:
    schema.py          — OpenAlex work -> normalized relational records + pyarrow schemas.
    io_parquet.py      — raw/interim/processed parquet layers + integrity checks.
    collector.py       — incremental, resumable historical collector (test/full modes).
    dedup.py           — deduplication + version linking.
    semantic_corpus.py — abstract reconstruction + anomaly/exclusion statistics.
    bibliometric.py    — reference edges (citing -> cited), no cumulative counts.
    temporal.py        — temporal separation (novelty / feature / emergence ranges).

Stage 2 produces CORPORA, not models: concept extraction, networks, link prediction
and disruption indices are intentionally NOT implemented here.
"""

WORKS_SELECT = (
    "id,doi,title,abstract_inverted_index,publication_year,publication_date,"
    "type,language,primary_topic,topics,referenced_works,referenced_works_count"
)
