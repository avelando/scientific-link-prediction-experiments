# Phase I (finish Stage 1) + Phase II (Stage 2) — corrections & build matrix

Verified against the current code before changing anything.

## Phase I — pending corrections

| # | Item | Verdict | Where | Fix | Test |
|---|---|---|---|---|---|
| I.1 | Weighted field classification not wired into the pipeline | **Confirmed** (only in `weighting.py` + unit tests, no CLI) | `cli/` | New `slpe-weighted-fields` CLI: real samples, primary vs weighted distribution, interdisciplinarity table | `test_weighting.py` (+ CLI smoke) |
| I.2 | Textual quality is conditional on `has_abstract,en` filter; no stratification | **Confirmed** | `quality_sampling.py` | Stratify by year (and type); document conditionality explicitly in outputs | `test_quality_sampling.py` |
| I.3 | Eligibility thresholds need justification; semantic vs bibliometric must stay separate | **Partially** (already split; justification missing) | `eligibility.py`, docs | Add written justification; keep `no_references_gate` as a bibliometric-only view | existing |
| I.4 | Conference-paper treatment must be an explicit, documented decision | **Confirmed** (sensitivity exists, decision not recorded) | `config`, docs | Record primary=article decision + alternative; note article/conference not mutually exclusive in OpenAlex | corpus-sensitivity CSV |
| I.5 | Domain selection must be reproducible + integrate weighting | **Partially** | `report.py` | Fold interdisciplinarity into recommendation | — |
| I.6 | Pagination checkpoint advances before consumer persists page | **Confirmed** | `client.py::paginate` | New `fetch_pages(on_page=...)`: cursor advances only after `on_page` returns (transactional) | `test_client.py` resume tests |

## Phase II — Stage 2 build

| # | Item | Module | Test |
|---|---|---|---|
| II.8 | Temporal config: full-history vs recent window (L) vs future | `config.py` (`full_history_start`) | `test_config.py` |
| II.9 | Historical collector (fields, batches, checkpoints, test/full modes) | `collection/collector.py` | `test_collector.py` |
| II.10 | Deduplication + version linking (DOI/ids; confirmed vs uncertain) | `collection/dedup.py` | `test_dedup.py` |
| II.11 | Semantic corpus prep (reconstruct abstracts, integrity, anomalies) | `collection/semantic_corpus.py` | `test_semantic_corpus.py` |
| II.12 | Bibliometric data prep (references, edge orientation; no cumulative counts) | `collection/bibliometric.py` | `test_bibliometric.py` |
| II.13 | Temporal separation enforcement | `collection/temporal.py` | `test_temporal_separation.py` |
| II.14 | Persistent parquet schema (raw/interim/processed) + integrity checks | `collection/schema.py`, `io_parquet.py` | `test_schema.py` |
| II.15 | Pilot collection (CS sample across periods; interrupt/resume; cost estimate) | `cli/collect_pilot.py` | pilot run (real, small) |
| II.16 | Interfaces/contracts for Stage 3 (no algorithms) | docstrings/schemas | — |

Out of scope (explicitly deferred): YAKE/KeyBERT, node2vec, networks, full disruption
indices, link prediction, RAG/LLMs.
