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

Implemented (this phase):

- **Stage 1 — field characterization & domain selection.** Profiles all 26 OpenAlex
  fields via aggregate queries (volume, year distribution, English-abstract share,
  reference availability, subfield diversity) and evaluates data-quality eligibility
  **before** any predictive evaluation.
- **OpenAlex client.** Polite-pool auth (+ optional key from `OPENALEX_API_KEY`),
  cursor pagination, backoff retries honouring `Retry-After`, persistent cache,
  resumable checkpoints, request/volume accounting.

Later stages (corpus build, concept extraction, networks, link prediction,
disruption) have reserved interfaces and config; see the traceability matrix. The
architecture is kept extensible toward the full M0–M5 comparison.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"          # add ,viz,nlp,graph as stages come online
copy .env.example .env           # then set OPENALEX_MAILTO (and optionally OPENALEX_API_KEY)
```

OpenAlex needs no key; set `OPENALEX_MAILTO` to use the faster "polite pool".
Credentials are read only from the environment, never from source or YAML.

## Run the field characterization

```powershell
$env:OPENALEX_MAILTO="you@example.org"
slpe-characterize-fields --config config/default.yaml
```

Outputs under `results/`:

| File | Contents |
|---|---|
| `field_characterization.parquet` / `.csv` | one row per field, all indicators |
| `field_eligibility.csv` | eligible? + failed data-quality criteria |
| `field_characterization.manifest.json` | params, snapshot date, request stats, versions |

Re-running is cheap — responses are cached on disk (`data/openalex_cache/`).

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
