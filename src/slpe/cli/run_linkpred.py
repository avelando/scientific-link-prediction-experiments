"""CLI: run the first real link-prediction comparison on title+abstract data.

Pipeline (per cut T in the configured cuts):
    sample works per year -> YAKE concepts (cached) -> novelty ledger (<=T) +
    feature network ([T-L+1, T]) -> emergent positives in (T, T+Delta_e] ->
    candidate sample (all positives + sampled negatives) -> score topological
    methods + baselines -> AUPRC / Precision@K / Recall@K, plus by-distance and
    same/different-community breakdowns.

Primary representation is title+abstract. Concepts come from the text (YAKE), never
from OpenAlex topics. Metrics are CONDITIONAL on the sampled candidate set.

Usage:
    python -m slpe.cli.run_linkpred [--config config/default.yaml]
        [--field 17] [--per-year 250] [--negatives 2000] [--seeds 3]
"""

from __future__ import annotations

import argparse
import json
import logging

from slpe.concepts.extract import extract_document_concepts
from slpe.config import CorpusConfig, load_config
from slpe.eval.metrics import evaluate_method, stratified_by
from slpe.linkpred.methods import score_all_methods
from slpe.logging_utils import configure_logging
from slpe.manifest import RunManifest
from slpe.networks.novelty import NoveltyLedger
from slpe.networks.semantic import (
    build_semantic_network,
    cooccurrence_counts,
    network_stats,
)
from slpe.openalex.abstracts import reconstruct_abstract
from slpe.openalex.client import OpenAlexClient
from slpe.pairs.candidates import (
    emergent_positive_pairs,
    enumerate_candidate_pairs,
    sample_candidate_pairs,
)

log = logging.getLogger("slpe.cli")
_SELECT = "id,title,abstract_inverted_index,publication_year"


def _sample_year(client, field_id, corpus_filter, year, k, seed):
    per_page = min(k, 200)
    out = []
    pages = (k + per_page - 1) // per_page
    for page in range(1, pages + 1):
        payload = client.get("works", {
            "filter": f"primary_topic.field.id:{field_id},{corpus_filter},publication_year:{year}",
            "sample": k, "seed": seed, "per-page": per_page, "page": page, "select": _SELECT})
        res = payload.get("results", [])
        out.extend(res)
        if len(res) < per_page:
            break
    return out


# Bump when concept extraction OR normalization rules change (invalidates cache).
_CONCEPT_PIPELINE_VERSION = "2"
_CONCEPT_TOP_K = 12
_CONCEPT_NGRAM = 3


def _load_or_build_concepts(client, cfg, field_id, per_year):
    """Return {doc_id: (year, [concepts])}, cached to parquet for reuse.

    The cache key encodes everything that affects the concepts: field, per-year
    sample size, seed, year range, extraction params and the pipeline/normalization
    version. Changing any of them yields a NEW cache file (old artifacts are kept).
    """
    import hashlib

    import pandas as pd

    key = (f"f{field_id}_py{per_year}_s{cfg.seed}_y{cfg.characterization.year_min}"
           f"-{cfg.characterization.year_max}_tk{_CONCEPT_TOP_K}_n{_CONCEPT_NGRAM}"
           f"_corpus{'-'.join(cfg.corpus.types)}_v{_CONCEPT_PIPELINE_VERSION}")
    digest = hashlib.sha256(key.encode()).hexdigest()[:10]
    cache = cfg.paths.data_interim / f"concepts_{field_id}_{digest}.parquet"
    if cache.exists():
        df = pd.read_parquet(cache)
        log.info("loaded %d cached concept docs", len(df))
        return {r.doc_id: (int(r.year), r.concepts.split("|") if r.concepts else [])
                for r in df.itertuples()}

    en_abs = "has_abstract:true,language:en" if cfg.corpus.require_english_abstract else "has_abstract:true"
    corpus_filter = f"type:{CorpusConfig.types_filter(cfg.corpus.types)},{en_abs}"
    rows = []
    for year in range(cfg.characterization.year_min, cfg.characterization.year_max + 1):
        works = _sample_year(client, field_id, corpus_filter, year, per_year, cfg.seed)
        for w in works:
            doc_id = str(w.get("id", "")).rstrip("/").split("/")[-1]
            abstract = reconstruct_abstract(w.get("abstract_inverted_index"))
            concepts = extract_document_concepts(
                w.get("title"), abstract, top_k=_CONCEPT_TOP_K, ngram=_CONCEPT_NGRAM)
            if concepts:
                rows.append({"doc_id": doc_id, "year": year, "concepts": "|".join(concepts)})
        log.info("year %d: %d docs with concepts", year, sum(1 for r in rows if r["year"] == year))
    df = pd.DataFrame(rows)
    df.to_parquet(cache, index=False)
    return {r.doc_id: (int(r.year), r.concepts.split("|")) for r in df.itertuples()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Link-prediction comparison.")
    parser.add_argument("--config", default="config/default.yaml")
    parser.add_argument("--field", type=int, default=17)
    parser.add_argument("--per-year", type=int, default=250)
    parser.add_argument("--negatives", type=int, default=2000,
                        help="negatives for the stratified fallback when the universe is too large.")
    parser.add_argument("--max-candidates", type=int, default=2_000_000,
                        help="above this universe size, fall back to stratified sampling.")
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--min-concept-docs", type=int, default=3)
    args = parser.parse_args(argv)

    import pandas as pd

    cfg = load_config(args.config)
    cfg.paths.ensure()
    configure_logging(cfg.paths.logs / "run_linkpred.log")

    L = cfg.temporal.history_window_years
    de = cfg.temporal.emergence_horizon_years
    manifest = RunManifest(run_name="linkpred_comparison", params={
        "field_id": args.field, "per_year": args.per_year, "negatives": args.negatives,
        "seeds": args.seeds, "L": L, "emergence_horizon": de,
        "min_concept_docs": args.min_concept_docs})

    with OpenAlexClient.from_config(cfg.openalex) as client:
        doc_concepts = _load_or_build_concepts(client, cfg, args.field, args.per_year)
        manifest.stats = client.stats.as_dict()

    rows, strat_rows, net_rows = [], [], []
    for cut in cfg.temporal.cuts:
        T = cut.cut
        hist = {d: cs for d, (y, cs) in doc_concepts.items() if y <= T}
        feat = {d: cs for d, (y, cs) in doc_concepts.items()
                if cut.history_start <= y <= T}
        future = {d: cs for d, (y, cs) in doc_concepts.items()
                  if T < y <= T + de}

        ledger = NoveltyLedger()
        ledger.add_documents(hist)
        g = build_semantic_network(feat, min_concept_docs=args.min_concept_docs)

        # Eligible concept universe: concepts appearing in >= min_concept_docs
        # documents of the OBSERVED HISTORY (<=T). This frequency floor keeps the
        # exhaustive enumeration tractable AND the concepts reliable; it is applied
        # with history-only information (no leakage).
        _, hist_counts = cooccurrence_counts(hist)
        eligible = {c for c, n in hist_counts.items() if n >= args.min_concept_docs}
        net_rows.append({"cut": cut.name, **network_stats(g),
                         "n_hist_docs": len(hist), "n_future_docs": len(future),
                         "n_eligible_concepts": len(eligible)})

        positives = emergent_positive_pairs(future, ledger)
        # EXHAUSTIVE candidate universe: every eligible (novelty-candidate) pair, with
        # real prevalence and no negative-sampling artifact (audit §4). Falls back to
        # stratified sampling only if the universe is too large.
        universe = enumerate_candidate_pairs(
            ledger, g, positives, eligible_concepts=eligible, max_candidates=args.max_candidates)
        sampled = universe is None
        if sampled:
            universe = sample_candidate_pairs(
                ledger, g, positives, n_negatives=args.negatives, seed=cfg.seed)
        log.info("cut %s: net=%d nodes/%d edges, candidates=%d, positives=%d (%s)",
                 cut.name, g.number_of_nodes(), g.number_of_edges(), len(universe),
                 sum(p.label for p in universe), "sampled" if sampled else "exhaustive")
        if sum(p.label for p in universe) == 0:
            log.warning("cut %s: no emergent positive pairs (need more data)", cut.name)
            continue

        pairs = [(p.a, p.b) for p in universe]
        labels = [p.label for p in universe]
        dist_bucket = ["disc" if p.distance < 0 else (f"d{p.distance}" if p.distance <= 3 else "d4+")
                       for p in universe]
        comm = ["same" if p.same_community else ("diff" if p.same_community is False else "na")
                for p in universe]

        # Deterministic methods: scored ONCE over the full universe (candidates are
        # exhaustive, so only the random baseline is stochastic).
        det_scores = score_all_methods(g, pairs, seed=cfg.seed)
        for method, sc in det_scores.items():
            if method == "random":
                continue
            rep = evaluate_method(labels, sc, ks=(10, 50, 100))
            rows.append({"cut": cut.name, "seed": 0, "method": method,
                         "candidates_mode": "sampled" if sampled else "exhaustive", **rep})
            # Stratified analysis for ALL methods (H2), not just two.
            for strat_name, strata in (("distance", dist_bucket), ("community", comm)):
                for key, m in stratified_by(strata, labels, sc, ks=(10, 50)).items():
                    strat_rows.append({"cut": cut.name, "method": method,
                                       "strat": strat_name, "group": key, **m})

        # Random baseline over multiple seeds (the only stochastic component).
        import random as _random
        for seed in range(args.seeds):
            rng = _random.Random(cfg.seed + seed)
            sc = [rng.random() for _ in pairs]
            rep = evaluate_method(labels, sc, ks=(10, 50, 100))
            rows.append({"cut": cut.name, "seed": seed, "method": "random",
                         "candidates_mode": "sampled" if sampled else "exhaustive", **rep})

    results = pd.DataFrame(rows)
    nets = pd.DataFrame(net_rows)
    strat = pd.DataFrame(strat_rows)
    results.to_csv(cfg.paths.results / "linkpred_results.csv", index=False)
    nets.to_csv(cfg.paths.results / "linkpred_networks.csv", index=False)
    strat.to_csv(cfg.paths.results / "linkpred_by_stratum.csv", index=False)

    # Aggregate AUPRC across seeds (mean +/- std) per method x cut.
    if len(results):
        agg = (results.groupby(["cut", "method"])["auprc"]
               .agg(["mean", "std", "count"]).reset_index()
               .sort_values(["cut", "mean"], ascending=[True, False]))
        agg.to_csv(cfg.paths.results / "linkpred_auprc_summary.csv", index=False)
        manifest.params["auprc_summary"] = json.loads(agg.to_json(orient="records"))

    manifest.hash_artifacts({"linkpred_results.csv": cfg.paths.results / "linkpred_results.csv"})
    manifest.write(cfg.paths.results / "linkpred_comparison.manifest.json")

    print("\n=== Network sizes per cut ===")
    print(nets.to_string(index=False))
    print("\n=== AUPRC by method and cut (mean over seeds) ===")
    if len(results):
        print(agg.to_string(index=False))
    else:
        print("No positives found — increase --per-year.")
    print(f"\nResults in {cfg.paths.results}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
