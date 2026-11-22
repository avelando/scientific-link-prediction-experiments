# Preliminary results — first link-prediction comparison (viability)

_Real run on OpenAlex Computer Science (field 17), title+abstract, 250 works/year
sampled 2013–2022 (reproducible seed), YAKE concepts. Three retrospective cuts,
3 seeds each. These are **viability** results, not the final study._

## What was computed (observed)

**Semantic networks** (concepts co-occurring in title+abstract; `min_concept_docs=3`):

| Cut | nodes | edges | density | giant comp. | emergent positives |
|---|---:|---:|---:|---:|---:|
| 2013–2017 → 2018 | 279 | 834 | 0.022 | 96% | 411 |
| 2015–2019 → 2020 | 285 | 880 | 0.022 | 95% | 462 |
| 2017–2021 → 2022 | 293 | 956 | 0.022 | 97% | 636 |

**Link prediction** — AUPRC (mean over 3 seeds), candidate set = all positives +
2,000 sampled negatives; prevalence 0.17 / 0.19 / 0.24 across cuts:

| Method | 2018 | 2020 | 2022 |
|---|---:|---:|---:|
| popularity (baseline) | 0.296 | 0.307 | 0.367 |
| preferential_attachment | 0.293 | 0.305 | 0.367 |
| adamic_adar | 0.217 | 0.224 | 0.287 |
| common_neighbors | 0.217 | 0.224 | 0.287 |
| jaccard | 0.217 | 0.224 | 0.287 |
| resource_allocation | 0.217 | 0.224 | 0.287 |
| random (baseline) | 0.172 | 0.192 | 0.241 |

All topological methods beat the random baseline in all three cuts; results are
stable across seeds (std < 0.01). Degree/popularity methods lead the neighbourhood
methods on these small, dense concept networks — a plausible, modest finding.

## Honest limitations (must be read with the numbers)

1. **Negative sampling is uniform, not yet stratified (project §4.2).** The
   stratified breakdown shows positives are concentrated among concepts that are
   connected in the feature network, while uniformly-sampled negatives are mostly
   *disconnected* pairs. So topological distance looks trivially predictive and the
   AUPRC partly reflects this positive/negative connectivity difference, not pure
   method quality. **The immediate next step is distance/community-stratified
   negative sampling with recorded inclusion probabilities** (the sampler already
   records distance, community and an inclusion-probability field — only the
   stratification is pending). Until then, H2 (distance/community dependence) is
   NOT validly tested.
2. **Small corpus.** 2,500 docs → ~280-concept networks. Vocabulary and positives
   are modest; numbers will shift with the 15k-document corpus.
3. **Sampled novelty.** "Emergent" = new co-occurrence in the *sampled* 2013–2022
   corpus, not globally novel in the literature.
4. **Retrospective.** Concepts come from current metadata; YAKE is deterministic and
   carries no post-cut knowledge, but the run is retrospective, not strictly ex ante.
5. **Metrics are conditional** on the sampled candidate set (not population
   estimates); prevalence, candidate counts and (for negatives) inclusion
   probabilities are recorded alongside every result.

## Not done here (next increments)

- Distance/community-stratified negative sampling (fixes limitation 1).
- node2vec and supervised logistic regression (chronological training).
- KeyBERT vs YAKE concept comparison (optional heavy deps).
- Full-text (PDF) vs title+abstract controlled comparison on the same documents.
- The three areas together (only CS run here) and the 15k corpus.
- Disruption availability diagnosis (project §4.4).

Artifacts: `results/linkpred_results.csv`, `linkpred_auprc_summary.csv`,
`linkpred_networks.csv`, `linkpred_by_stratum.csv`, `linkpred_comparison.manifest.json`.
