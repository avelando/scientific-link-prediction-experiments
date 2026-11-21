# Traceability matrix — project requirements ↔ experimental decisions ↔ code

This matrix links each methodological requirement to (a) its source in the PhD
research project (`Avelar_Project.pdf`), (b) the concrete decision taken for the
**preliminary experiments**, and (c) the code component that implements it.

Legend for **Status** (requirement ORIGIN):

- **P (Project)** — a decision already fixed in the research project; we implement it as written.
- **E (Extension)** — a preliminary-experiment choice we are proposing now; justified below or in the referenced note.
- **L (Later)** — part of the full PhD methodology, intentionally *not* implemented in this phase; architecture kept extensible for it.

Legend for **Impl.** (implementation status — distinct from origin):

- **done+tested** — implemented and covered by automated tests.
- **done** — implemented, lightly or not yet unit-tested.
- **interface** — config/placeholder/docstring only; no behaviour yet.
- **planned** — not started (Stage ≥ 2).

Any deviation from a project decision is flagged explicitly in the **Notes** column.
See also [`audit_response_matrix.md`](audit_response_matrix.md) for the Stage-1 audit remediation.

### Stage-1 implementation status (this phase)

| Area | Impl. | Where |
|---|---|---|
| OpenAlex client (auth, paging, retries, cache **envelope+provenance**, checkpoints, accounting) | done+tested | `openalex/client.py`, `tests/test_client.py` |
| Abstract reconstruction + integrity diagnostics | done+tested | `openalex/abstracts.py`, `tests/test_abstracts.py` |
| Config (typed, dotenv, validation, temporal protocol) | done+tested | `config.py`, `tests/test_config.py` |
| Corpus types (configurable) + 3 coverage levels (semantic/bibliometric/DI-candidate) | done+tested | `characterization/fields.py`, `tests/test_characterization.py` |
| Eligibility (no subfield gate) + sensitivity + legacy reproduction | done+tested | `characterization/eligibility.py`, `tests/test_eligibility.py` |
| Weighted field attribution (Brito adaptation) | done+tested | `characterization/weighting.py`, `tests/test_weighting.py` |
| Textual-quality sampling (Wilson CIs) | done+tested | `characterization/quality_sampling.py`, `tests/test_quality_sampling.py` |
| Log redaction / credential hygiene | done+tested | `logging_utils.py`, `tests/test_security.py` |
| Report from frozen artifacts (figures + markdown + recommendation) | done | `characterization/report.py`, CLIs |
| Weighted field attribution wired into a CLI + real run | done+tested | `cli/weighted_fields.py`, `tests/test_weighting.py` |
| Stratified (by-year) textual quality | done | `cli/sample_quality.py --by-year` |
| Selection rationale (eligibility + conference + domains) | done | `docs/stage1_selection_rationale.md` |
| Manifests (git commit, config + artifact hashes) | done | `manifest.py` |

### Stage-2 implementation status (collection)

| Area | Impl. | Where |
|---|---|---|
| Temporal config: full-history / feature-window / emergence ranges | done+tested | `config.py` (`TemporalConfig.*_range`), `tests/test_config.py` |
| Transactional page collector (cursor advances after persist) | done+tested | `openalex/client.py::fetch_pages`, `tests/test_client.py` |
| Historical collector (raw parquet, batches, resume, test/full modes) | done+tested | `collection/collector.py`, pilot run |
| Normalized schema (publications/topics/references) | done+tested | `collection/schema.py`, `tests/test_collection.py` |
| Parquet layers (raw/interim/processed) + integrity | done+tested | `collection/io_parquet.py` |
| Deduplication + version linking (confirmed/uncertain) | done+tested | `collection/dedup.py` |
| Semantic corpus prep + exclusion stats | done+tested | `collection/semantic_corpus.py` |
| Bibliometric edges (citing→cited, external kept) | done+tested | `collection/bibliometric.py` |
| Temporal separation / no-leakage enforcement | done+tested | `collection/temporal.py` |
| Pilot CLI (real run, idempotent resume, cost estimate) | done | `cli/collect_pilot.py` |
| Concepts, networks, link prediction, disruption indices, RAG/LLM | planned | Stage ≥ 3 |

---

## 0. Cross-cutting: temporal protocol and leakage control

| # | Requirement (source) | Status | Decision for preliminary experiments | Code component |
|---|---|---|---|---|
| 0.1 | Distinguish history window `L`, emergence horizon `Δe`, disruption horizon `Δd` (§4.1, §4.5, eq. 3) | P | `L=5`, `Δe=1`, `Δd=3` as defaults in `config.temporal`; `L∈{3,5,7}` as later sensitivity | `config/default.yaml`, `slpe.config` |
| 0.2 | Features use only information available up to cut `T`; outcomes observed strictly after (§4.5, Fig. 2) | P | Every cut stores `history_start/cut/emergence_year`; collection filters by publication date, never "current" cumulative values | `slpe.config.TemporalCut` (+ enforced in later feature stages) |
| 0.3 | Train/val/test obey `T_tr+Δe+Δd ≤ T_val` and `T_val+Δe+Δd ≤ T_te` (eq. 3) | P | Encoded as a validator over configured cuts; preliminary cuts are *repeated retrospective evaluations*, not auto-treated as independent splits | `slpe.config.validate_temporal_protocol` (stage-by-stage) |
| 0.4 | Pretrained encoders / current OpenAlex classifications may leak post-cut knowledge → label such runs "retrospective" (§4.5) | P | Runs are tagged `ex_ante` vs `retrospective` in run manifests; KeyBERT/embeddings flagged retrospective by default | run manifest schema (`slpe.manifest`, stage 3+) |
| 0.5 | Publication dates ≠ metadata retrieval dates; cumulative citation counts not usable as historical features (§4.5) | P | Characterization records the data snapshot date in every manifest | `slpe.manifest`, `scripts`/CLI output |

## 1. Data source and corpus construction (§4.1)

| # | Requirement (source) | Status | Decision | Code component |
|---|---|---|---|---|
| 1.1 | OpenAlex as primary source: ids, titles, abstracts, dates, citation relations (§4.1) | P | `httpx`-based client with polite pool + optional key, pagination, retries, persistent cache, checkpoints/resume | `slpe.openalex.client.OpenAlexClient` |
| 1.2 | Focal corpus: works with English title+abstract and usable dates (§4.1) | P | Filters `has_abstract:true, language:en`; abstract reconstructed from inverted index | `slpe.openalex.abstracts`, collection stage (later) |
| 1.3 | Deduplicate versions, preserve dates, avoid back-dating later content (§4.1) | L (interface now) | Dedup key design documented; enforced at corpus build; characterization counts are aggregate (dedup not yet needed) | `slpe.corpus.dedup` (stage 2) |
| 1.4 | Use OpenAlex thematic filters to delimit corpus, but **not** as semantic-network vertices (§4.1) | P | Field membership via `primary_topic.field.id` / `topics.field.id`; concepts come from text, never topics | characterization uses topics; network vertices = extracted concepts (stage 3–4) |
| 1.5 | Record exclusions and coverage limitations (§4.1) | P | Every characterization row reports coverage fractions and measured denominators | `slpe.characterization.fields` |

## 1a. Domain selection — adaptation of Brito et al. (2023) (Stage 1 instruction)

| # | Requirement (source) | Status | Decision | Code component |
|---|---|---|---|---|
| 1a.1 | Use Brito et al. (2023) MAG field-hierarchy weighting as the reference principle | P (reference) | Adapt the per-paper field weight `w_P(f_top)` to OpenAlex topic scores; present as adaptation, not literal MAG formula | `slpe.characterization.weighting` (next step) |
| 1a.2 | Primary classification = field of `primary_topic`; complementary weighted distribution across topic fields | E | Two views: (i) primary-topic field counts; (ii) score-weighted field membership from `topics[].score` | `slpe.characterization.fields` |
| 1a.3 | Characterize all **26 fields**: volume, year distribution, English-abstract share, reference availability, subject diversity | E | Aggregate `group_by`/`meta.count` queries only — no bulk downloads | `slpe.characterization.fields.characterize_field` |
| 1a.4 | Eligibility thresholds defined on **data quality**, before any predictive evaluation | E | Thresholds in `config.characterization.eligibility`; selection script ranks eligible fields | `slpe.characterization.eligibility` (next step) |
| 1a.5 | Recommend 3 areas (representativeness, diversity, feasibility); start from CS, Physics&Astro, Medicine but examine others | P | CS(17)/Physics&Astro(31)/Medicine(27) flagged as candidates; all 26 measured and compared | `config.characterization.candidate_field_ids`, selection report |

## 2. Temporal corpora (Stage 2) — **L for now**, interfaces defined

| # | Requirement | Status | Decision | Code |
|---|---|---|---|---|
| 2.1 | Three cuts: 2013–17→2018, 2015–19→2020, 2017–21→2022 (Stage 2) | P | Encoded in `config.temporal.cuts` | `slpe.config` |
| 2.2 | Preserve full pre-`T` co-occurrence history for novelty check, independent of `L` (§4.1) | P | Separate "all history before T" ledger vs "L-window predictor network" | `slpe.networks.novelty_ledger` (stage 4) |

## 3. Concept extraction and normalization (§4.1, Stage 3) — **L**

| # | Requirement | Status | Decision | Code |
|---|---|---|---|---|
| 3.1 | Compare YAKE vs KeyBERT on titles+abstracts (§4.1) | L | Extras declared (`nlp`); pluggable extractor interface | `slpe.concepts.extract` |
| 3.2 | Lexical normalization, acronyms, equivalences; no retrospective vocabulary injection (§4.1) | L | Per-cut frozen vocabulary applied forward | `slpe.concepts.normalize` |

## 4. Scientific networks (§4.1, Stage 4) — **L**

| # | Requirement | Status | Decision | Code |
|---|---|---|---|---|
| 4.1 | Semantic network: undirected, weighted (edge weight = #papers with the pair) (§4.1) | L | igraph/NetworkX builder from doc–concept records | `slpe.networks.semantic` |
| 4.2 | Citation network: directed, unweighted (citing→cited); in-degree + PageRank aggregated to concepts (§4.1) | L | Separate builder; bibliometric features via associated docs | `slpe.networks.citation` |

## 5. Candidate pairs and link prediction (§4.2, Stage 5) — **L**

| # | Requirement | Status | Decision | Code |
|---|---|---|---|---|
| 5.1 | Unit = unordered pair of concepts known at `T`, never co-occurred in observed history (§4.2) | P | Pair generator over per-cut vocabulary minus novelty ledger | `slpe.pairs.candidates` |
| 5.2 | Emergence positive if co-occur in `(T, T+Δe]` (§4.2) | P | Outcome labeller | `slpe.pairs.outcomes` |
| 5.3 | Stratified probabilistic sampling by topological distance + community, incl. disconnected components; record inclusion probabilities; same candidates for all methods (§4.2) | P | Sampler logs inclusion probability per candidate; shared sample id | `slpe.pairs.sampling` |

## 6. Link-prediction method families (§4.2, Stage 6) — **L**, matrix authored

| # | Requirement | Status | Decision | Code |
|---|---|---|---|---|
| 6.1 | Core (mandatory): Common Neighbors, Jaccard, Adamic–Adar, Preferential Attachment, logistic regression (neighbourhood/degree/strength/distance), node2vec (§4.2) | P | Implement first; symmetric pair features; chronological hyperparameter selection | `slpe.linkpred.*` |
| 6.2 | Extensions: Resource Allocation, weighted measures, Katz, Local Path, Personalized PageRank, DeepWalk, struc2vec, RF/GBM, hybrid text+topo+temporal+biblio | E | Prioritized extension list; added incrementally | `slpe.linkpred.*` |
| 6.3 | Complex models (GraphSAGE, GCN, GAE, GAT, SEAL): assess cost/benefit before implementing (§ instruction) | L | Deferred; documented in method matrix | `docs/method_matrix.md` (stage 6) |

## 7. Prediction evaluation (§4.5, Stage 7) — **L**

| # | Requirement | Status | Decision | Code |
|---|---|---|---|---|
| 7.1 | AUPRC, Precision@K, Recall@K; report prevalence, coverage, denominators; inclusion-weighting for population estimates (§4.5) | P | Metrics module distinguishes sample-conditional vs population estimates | `slpe.eval.metrics` |
| 7.2 | Analyse by distance, same/different community, disconnected components; random + popularity baselines; multiple seeds + dispersion (§4.5) | P | Stratified reporting; fixed `K` not retuned on test | `slpe.eval.report` |

## 8. Disruption availability study (§4.4, Stage 8) — **exploratory this phase**

| # | Requirement | Status | Decision | Code |
|---|---|---|---|---|
| 8.1 | Disruption index `D=(N_F−N_B)/(N_F+N_B+N_R)`, each work counted once (§4.4, eq. 1) | P | Verified on small synthetic graphs with hand-checked values | `slpe.disruption.index` (+ tests) |
| 8.2 | Connection label = **median** of `D` over materializing, measurable works; record count + valid fraction (§4.4, eq. 2) | P | Median primary; mean / first-occurrence as robustness | `slpe.disruption.label` |
| 8.3 | Fixed `Δd` per publication date; record missing refs / incomplete horizon / insufficient coverage / undefined separately; never assign D=0 to unmeasurable (§4.4) | P | Measurability flags, not imputation | `slpe.disruption.availability` |
| 8.4 | Variants DI5, DI1-noR per Leibel & Bornmann (2024) — verify definitions before implementing | E | Documented, guarded behind definition checks | `slpe.disruption.variants` |

## 9. Diagnosis of non-selected emergent connections (§3 Q4, Stage 9) — **L** |

| # | Requirement | Status | Decision | Code |
|---|---|---|---|---|
| 9.1 | Characterize pairs that emerged with high disruption but fell outside top-`K`; threshold set on dev data; diagnostic only, no post-test refit (§ Q4) | P | Diagnostic report keyed off stage 7/8 outputs | `slpe.diagnosis` |

## 10. Full-methodology readiness (§4.3–4.5, Table 1) — **L**

| # | Requirement | Status | Decision | Code |
|---|---|---|---|---|
| 10.1 | Six configs M0–M5; central comparison M4 vs M5 with shared examples/evidence/encoder/regressor/budget (Table 1) | L | Config schema reserves M0–M5; not run now | `config` placeholders, `slpe.disruption.configs` |
| 10.2 | Regression metrics MAE, RMSE, Spearman (§4.5 Q3) | L | Reserved | `slpe.eval.regression` |
| 10.3 | **Do not** claim the central hypothesis is confirmed by preliminary experiments | P | Reporting language constrained in the "Preliminary Results & Feasibility" write-up | `docs/preliminary_results.md` (final deliverable) |

## Engineering requirements (Stage: implementation)

| # | Requirement | Status | Decision | Code |
|---|---|---|---|---|
| I.1 | Modular, typed, documented, testable `src/` layout; notebooks for exploration only | P | `src/slpe/` package; CLI entrypoints; pytest suite | repo layout |
| I.2 | YAML config centralizes areas/windows/hyperparameters/seeds/paths | P | `config/default.yaml` + `slpe.config` loader | done |
| I.3 | OpenAlex: read docs first; env `OPENALEX_API_KEY`; pagination, backoff retries, rate-limit respect, persistent cache, checkpoints, resume; log request counts/volume | P | Implemented in client; never invent data on failure | `slpe.openalex.client` |
| I.4 | Parquet for intermediate data; avoid loading large artifacts fully into memory | P | Parquet writers; streamed cursor pagination | `slpe.io.parquet`, client cursor paging |
| I.5 | Tests: abstract reconstruction, dedup, normalization, edge creation, novelty preservation, temporal cuts, pair symmetry, candidate selection, metrics, disruption on synthetic graphs, sampling inclusion-probability logging | P | Implemented incrementally alongside each component | `tests/` |
| I.6 | Logs, manifests (data/dependency versions), result files with per-experiment params, error records | P | Manifest + logging utilities | `slpe.manifest`, `slpe.logging_utils` |

---

### Open issues / decisions flagged for the advisor

1. **Weighted field membership formula.** Brito et al. (2023) weight a paper's field by walking the MAG DAG upward (`w_P(f_top)` averaged over subfields, split across parents). OpenAlex already exposes per-topic `score`s and a fixed topic→subfield→field→domain tree, so we adapt rather than replicate: weighted membership uses `topics[].score` normalized per work. This is an **E** decision — recorded as an adaptation, pending your confirmation.
2. **Eligibility thresholds (1a.4).** Initial numeric thresholds are placeholders in `config`; they must be finalized on development data before the main evaluation and must not reference test accuracy.
3. **Abstract availability vs reconstruction.** OpenAlex stores abstracts as an inverted index; `has_abstract:true` counts presence, but a few records have corrupt indices. Characterization reports the `has_abstract` fraction; the exact reconstructable fraction is measured on samples (documented per field).
