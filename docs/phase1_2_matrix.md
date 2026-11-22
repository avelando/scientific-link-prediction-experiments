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

## Phase A corrections — applied (this round)

| Audit item | Status | Note |
|---|---|---|
| 4.1 capped collection marked "done" | **fixed** | checkpoint `status` ∈ {complete, partial, interrupted, failed}; capped→partial continues on resume |
| 4.2 dataset identity | **fixed** | `dataset_manifest.json` with query id; refuses mixing a different query into a dataset dir |
| 4.3 scalability (to_table/to_pandas) | **partially** | batched part-file writes + `iter_batches`/`dataset_count` streaming; dedup stays in-memory (bounded at ~100k rows — documented) |
| 4.4 external references naming | **fixed** | renamed to cited-in/outside **observed corpus**; not "outside the field" |
| 4.5 dedup id-mapping | **fixed** | `canonical_mapping` + `apply_canonical_mapping` applied to references (and topics) |
| 4.6 provenance | **present** | response `Date` (cache) vs `collected_utc` (row) vs `run_utc` (manifest) distinguished |
| 4.7 per_page / full_history_start | **fixed** | per_page=200 is the OpenAlex cursor max (kept); `full_history_start` set to 2013 + validated |

## Phase B pilot — measured (real run, 12 works/field)

Free OA PDFs only; paid content API off. Funnel (indicative, small sample):

| Field | OA availability | with PDF URL | valid PDF | text extracted |
|---|---:|---:|---:|---:|
| Computer Science (17) | 0.62 | 12/12 | 5/12 | 5/12 |
| Physics & Astronomy (31) | 0.72 | 12/12 | 8/12 | 8/12 |
| Medicine (27) | 0.69 | 12/12 | 5/12 | 5/12 |

Mean processable rate ≈ 0.50; ≈ 1.0 MB per valid PDF. Projection to 99k processable
docs: ≈ 101 GB storage and ≈ 198k works to sample. Rates are from a SMALL sample —
indicative, not population estimates. The gap from "PDF URL" (100%) to "valid+text"
(~50%) is real attrition (403/404, HTML/landing pages, scanned/no-text, corrupt).

## Still pending (next increments — Phases C–F, not done here)

Concept extraction (YAKE vs KeyBERT), semantic/citation network construction,
candidate pairs + emergence labels, link-prediction methods + evaluation (H1/H2/H3),
and the disruption availability diagnosis. H1/H2/H3 are **not** yet tested.
