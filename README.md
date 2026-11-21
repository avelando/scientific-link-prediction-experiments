# scientific-link-prediction-experiments

Preliminary experiments for the PhD project **"Explainable Prediction of Emerging
Scientific Connections and Estimation of Bibliometric Disruption"** (A. R. de Sousa,
adv. D. R. Amancio, ICMC/USP).

This repository implements the **feasibility experiments** that precede the full
methodology. The scientific specification is the project PDF; every decision is
traced to it in [`docs/traceability_matrix.md`](docs/traceability_matrix.md).

> These experiments probe **viability** (data coverage, method behaviour,
> disruption-label availability). They are **not** a validation of the central
> hypothesis about LLM-generated justifications, which is evaluated later.

## Current status

Implemented (this phase — Stage 1 only):

- **Field characterization & domain selection.** Profiles all 26 OpenAlex fields via
  aggregate queries, with a **configurable corpus type** (default `article`) and
  **three explicit coverage levels** — semantic (text), bibliometric (references),
  and a DI-candidate note — so they are never conflated. Evaluates data-quality
  eligibility **before** any predictive evaluation.
- **Eligibility without a subfield-count gate.** Subfield count is descriptive only
  (reported with normalized entropy); an absolute minimum unfairly excluded fields
  with coarse taxonomies (e.g. Physics and Astronomy). Ships a **sensitivity
  analysis** and a **legacy-criteria reproduction** of the audited numbers.
- **Weighted field attribution** (OpenAlex adaptation of Brito et al. 2023): primary
  vs `topics[].score`-weighted membership, with a multidisciplinarity view.
- **Textual-quality sampling**: inspects real sampled works (reconstructable text,
  language, tokens, references, dates) with Wilson confidence intervals — separating
  sampled estimates from exact aggregate counts.
- **OpenAlex client**: polite-pool auth (+ optional key), cursor pagination, backoff
  retries honouring `Retry-After`, a **provenance-carrying cache** (fetch time,
  server `Date`, query id, collector version; optional TTL/refresh), query-bound
  resumable checkpoints, and request/volume accounting.
- **Credential hygiene**: secrets only from the environment (`.env` via dotenv), and
  **log redaction** of `api_key`/`mailto` in URLs.

Later stages (concepts, networks, link prediction, disruption, RAG) are **not**
implemented; interfaces/config are reserved. See
[`docs/traceability_matrix.md`](docs/traceability_matrix.md) and
[`docs/audit_response_matrix.md`](docs/audit_response_matrix.md).

> **Security note.** Treat any OpenAlex key previously placed in a `.env` and shared
> (e.g. zipped) as **compromised — rotate/revoke it** at your OpenAlex account. This
> repo never stores keys in source, ignores `.env` in git, redacts secrets from logs,
> and `export-ignore`s `.env` from `git archive`. Rotation must be done by you; the
> code cannot and does not revoke keys.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env
```

Then edit `.env` and set `OPENALEX_MAILTO` (and optionally `OPENALEX_API_KEY`).
Matplotlib and python-dotenv are core dependencies, so the report and `.env`
loading work out of the box. OpenAlex needs no key; `OPENALEX_MAILTO` uses the
faster "polite pool". Credentials are read only from the environment (the code
loads `.env` automatically), never from source or YAML. For an exact replication
environment, freeze resolved versions with `pip freeze > requirements.lock.txt`.

## Run Stage 1

```powershell
slpe-characterize-fields --config config/default.yaml --corpus-sensitivity
```

```powershell
slpe-sample-quality --config config/default.yaml --n 384
```

```powershell
slpe-report-fields --config config/default.yaml
```

The first characterizes all 26 fields (add `--limit N` for a smoke test — it
restricts fields *before* issuing queries; `--refresh-cache` bypasses the cache).
The second samples real works per candidate field for textual-quality validation.
The third re-renders figures + the write-up strictly from the frozen result files.

Outputs under `results/`:

| File | Contents |
|---|---|
| `field_characterization.csv` / `.parquet` | one row per field, all indicators |
| `field_characterization_years.csv` | per-field, per-year counts |
| `field_eligibility.csv` | semantic + bibliometric verdicts, per-criterion values |
| `field_sensitivity.csv` | how the eligible set shifts per criterion |
| `field_corpus_sensitivity.csv` | article vs +conference corpus (`--corpus-sensitivity`) |
| `legacy_eligibility_reproduction.csv` | audit's 6-vs-14 check on the original data |
| `textual_quality_sampling.csv` | sampled text-quality coverage + Wilson CIs |
| `preliminary_results_stage1.md` | numbers-only write-up + domain recommendation |
| `figures/*.png` | eligibility, coverage, yearly volume |
| `*.manifest.json` | params, provenance, git commit, artifact hashes, request stats |

Two more Stage-1 analyses:

```powershell
slpe-weighted-fields --config config/default.yaml --n 500
```

```powershell
slpe-sample-quality --config config/default.yaml --n 300 --by-year --n-per-year 80
```

`slpe-weighted-fields` compares primary vs score-weighted (interdisciplinary) field
attribution; `--by-year` stratifies the textual-quality sample across periods. See
[`docs/stage1_selection_rationale.md`](docs/stage1_selection_rationale.md) for the
eligibility, conference-type and domain-selection rationale.

`results/legacy/` preserves the original (pre-audit) outputs for comparison.
Re-running is cheap — responses are cached with provenance in
`data/openalex_cache/`. The manifest time is the **code run time**, not a frozen
DB snapshot; per-response fetch time + server `Date` live in the cache envelopes.

## Stage 2 — historical corpus collection

Stage 2 builds the historical corpora (collection → dedup → semantic corpus →
citation edges → temporal partition). It produces **corpora, not models** — concept
extraction, networks, link prediction and disruption are not implemented yet.

Run a bounded, reproducible **pilot** (safe by default — never starts a large
download implicitly):

```powershell
slpe-collect-pilot --config config/default.yaml --field 17 --max-records 600
```

Outputs (under `data/`, git-ignored):

| Layer | Path | Contents |
|---|---|---|
| raw | `data/raw/pilot_field17/{publications,topics,references}/` | normalized records, batched parquet part files |
| interim | `data/interim/pilot_field17/` | deduplicated publications + linkage log |
| processed | `data/processed/pilot_field17/` | semantic corpus + citation edges |

The pilot reports collected/after-dedup/semantic counts, exclusions, citation-edge
split (internal vs external), per-cut temporal partitions, integrity issues, and a
**full-collection cost estimate** (requests + storage). Collection is resumable and
idempotent: a crash re-fetches only the in-flight page (cursor advances **after**
each page is persisted), and re-running a finished collection does not duplicate.
Temporal ranges are distinct: full observed history (novelty) ⊇ recent L-window
(features), with the future emergence window kept separate as labels. A full
collection requires explicit flags (`--full --i-understand-full-collection`).

## Repository layout

```
config/default.yaml          # areas, temporal windows, hyperparameters, seeds, paths
docs/traceability_matrix.md  # requirement -> decision -> code, with P/E/L status
src/slpe/
  config.py                  # typed config + temporal-protocol validator
  manifest.py                # reproducibility manifests
  openalex/                  # client, abstract reconstruction
  characterization/          # Stage 1: field profiling + eligibility
  cli/                       # command-line entrypoints
tests/                       # pytest suite (abstracts, config, client, characterization)
```

## Tests

```powershell
pytest -q
```

## Reproducibility & temporal protocol

- History window `L`, emergence horizon `Δe`, disruption horizon `Δd` are distinct
  and configured in `config/default.yaml`.
- Features use only information available up to each cut `T`; outcomes are observed
  strictly after. Current OpenAlex metadata and pretrained encoders may embed
  post-cut knowledge, so such runs are labelled **retrospective** in manifests.
- Every result carries a manifest (snapshot date, params, request stats, versions).
