"""CLI: pilot historical collection for one candidate field (default: Computer Science).

Runs the full Stage-2 flow on a bounded, reproducible sample:
    collect (raw parquet) -> dedup -> semantic corpus -> citation edges ->
    temporal partition -> integrity checks -> counts + cost estimate.

Safety: never starts a large download implicitly. A cap (``--max-records``) applies
unless ``--full`` AND ``--i-understand-full-collection`` are BOTH given; even then a
hard safety ceiling requires the explicit acknowledgement flag.

Usage:
    python -m slpe.cli.collect_pilot [--config config/default.yaml]
        [--field 17] [--max-records 600]
"""

from __future__ import annotations

import argparse
import logging

from slpe.collection.bibliometric import citation_edges, edge_stats
from slpe.collection.collector import HistoricalCollector
from slpe.collection.dedup import apply_canonical_mapping, canonical_mapping, deduplicate
from slpe.collection.io_parquet import (
    check_publications_integrity,
    dataset_dir,
    read_dataset,
)
from slpe.collection.semantic_corpus import build_semantic_corpus
from slpe.collection.temporal import partition_by_cut
from slpe.config import CorpusConfig, load_config
from slpe.logging_utils import configure_logging
from slpe.manifest import RunManifest
from slpe.openalex.client import OpenAlexClient

_SAFETY_CEILING = 50_000  # refuse larger pilots without explicit acknowledgement


def _estimate_full_cost(n_total_available: int, bytes_per_work: float, per_page: int = 200) -> dict:
    n_requests = (n_total_available + per_page - 1) // per_page
    est_bytes = int(n_total_available * bytes_per_work)
    return {
        "works_available_estimate": n_total_available,
        "requests_estimate": n_requests,
        "download_bytes_estimate": est_bytes,
        "download_gb_estimate": round(est_bytes / 1e9, 2),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pilot historical collection.")
    parser.add_argument("--config", default="config/default.yaml")
    parser.add_argument("--field", type=int, default=17, help="field id (default 17 = CS).")
    parser.add_argument("--max-records", type=int, default=600)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--i-understand-full-collection", action="store_true")
    args = parser.parse_args(argv)

    import pandas as pd

    cfg = load_config(args.config)
    cfg.paths.ensure()
    configure_logging(cfg.paths.logs / "collect_pilot.log")
    log = logging.getLogger("slpe.cli")

    max_records = args.max_records
    if args.full:
        if not args.i_understand_full_collection:
            print("Refusing full collection without --i-understand-full-collection.")
            return 2
        max_records = None
    if max_records is not None and max_records > _SAFETY_CEILING and not args.i_understand_full_collection:
        print(f"--max-records {max_records} exceeds safety ceiling {_SAFETY_CEILING}; "
              "pass --i-understand-full-collection to proceed.")
        return 2

    en_abs = "has_abstract:true,language:en" if cfg.corpus.require_english_abstract else "has_abstract:true"
    corpus_filter = f"type:{CorpusConfig.types_filter(cfg.corpus.types)},{en_abs}"
    fid = args.field
    dataset_name = f"pilot_field{fid}"
    ymin, ymax = cfg.characterization.year_min, cfg.characterization.year_max

    base = cfg.paths.data_raw.parent  # data/
    checkpoint = cfg.paths.data_interim / f"{dataset_name}.checkpoint.json"
    manifest = RunManifest(run_name="pilot_collection",
                           params={"field_id": fid, "max_records": max_records,
                                   "corpus_filter": corpus_filter, "year_range": [ymin, ymax],
                                   "base_dir": str(base)})

    with OpenAlexClient.from_config(cfg.openalex) as client:
        collector = HistoricalCollector(client, base_dir=base, layer="raw")
        result = collector.collect_field(
            fid, year_min=ymin, year_max=ymax, corpus_filter=corpus_filter,
            dataset_name=dataset_name, checkpoint_path=checkpoint, max_records=max_records,
        )
        # Estimate total available (uncapped) for the cost projection.
        total_available = client.count(
            "works", f"primary_topic.field.id:{fid},"
            f"from_publication_date:{ymin}-01-01,to_publication_date:{ymax}-12-31,{corpus_filter}")
        manifest.stats = client.stats.as_dict()

    # Load raw publications and run the preparation pipeline.
    pub_table = read_dataset(result.pub_dir)
    refs_table = read_dataset(result.refs_dir)
    pub_df = pub_table.to_pandas() if pub_table.num_rows else pd.DataFrame()
    refs_df = refs_table.to_pandas() if refs_table.num_rows else pd.DataFrame(
        columns=["citing_id", "cited_id"])

    integrity = check_publications_integrity(pub_table) if pub_table.num_rows else ["empty"]
    canonical, linkage = deduplicate(pub_df)
    # Apply the canonical id-mapping to the references so edges use canonical ids
    # consistently (audit 4.5).
    mapping = canonical_mapping(linkage)
    refs_df = apply_canonical_mapping(refs_df, mapping, ["citing_id", "cited_id"])
    corpus, cstats = build_semantic_corpus(canonical)
    edges = citation_edges(refs_df)
    estats = edge_stats(edges, set(canonical["work_id"]))

    # Temporal partitions per cut (predictor / emergence / later).
    partitions = {}
    for cut in cfg.temporal.cuts:
        part = partition_by_cut(corpus, cfg.temporal, cut)
        partitions[cut.name] = {
            "predictor": len(part.predictor),
            "emergence": len(part.emergence),
            "future_other": len(part.future_other),
        }

    # Persist interim/processed artifacts.
    interim_dir = dataset_dir(base, "interim", dataset_name)
    processed_dir = dataset_dir(base, "processed", dataset_name)
    canonical.to_parquet(interim_dir / "publications_dedup.parquet", index=False)
    linkage.to_parquet(interim_dir / "linkage.parquet", index=False)
    corpus.to_parquet(processed_dir / "semantic_corpus.parquet", index=False)
    edges.to_parquet(processed_dir / "citation_edges.parquet", index=False)

    # Cost estimate from measured bytes/work.
    bytes_per_work = (manifest.stats["bytes_downloaded"] / result.n_works) if result.n_works else 0.0
    cost = _estimate_full_cost(total_available, bytes_per_work)

    report = {
        "collected_raw": result.n_works,
        "pages": result.n_pages,
        "integrity_issues": integrity,
        "after_dedup": len(canonical),
        "version_links": int((linkage["confidence"] == "confirmed").sum()) if len(linkage) else 0,
        "uncertain_dupe_flags": int((linkage["confidence"] == "uncertain").sum()) if len(linkage) else 0,
        "semantic_corpus": cstats.n_included,
        "exclusions": cstats.exclusions,
        "citation_edges": estats.n_edges,
        "edges_cited_in_corpus": estats.n_cited_in_corpus,
        "edges_cited_outside_corpus": estats.n_cited_outside_corpus,
        "temporal_partitions": partitions,
        "full_collection_cost_estimate": cost,
    }
    manifest.params["pilot_report"] = report
    manifest.hash_artifacts({
        "semantic_corpus.parquet": processed_dir / "semantic_corpus.parquet",
        "citation_edges.parquet": processed_dir / "citation_edges.parquet",
    })
    manifest.write(cfg.paths.results / "pilot_collection.manifest.json")

    log.info("pilot report: %s", report)
    print("\n=== Pilot collection report (field %d) ===" % fid)
    for k, v in report.items():
        print(f"  {k}: {v}")
    print(f"\nRaw: {base}/raw/{dataset_name}/  Interim: {interim_dir}  Processed: {processed_dir}")
    print(f"Manifest: {cfg.paths.results / 'pilot_collection.manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
