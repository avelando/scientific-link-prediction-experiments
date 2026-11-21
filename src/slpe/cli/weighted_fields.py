"""CLI: compare primary vs score-weighted field attribution (Brito-style adaptation).

For each field, draws a reproducible sample of real works and computes:
    * the primary-topic field distribution (one field per work), and
    * the score-weighted distribution across the fields of each work's topics.

Reports the fraction of multidisciplinary works and where each field's works
"bleed" into other fields — a view of interdisciplinarity the primary view hides.
OpenAlex topic scores are used only as relative weights (NOT calibrated
probabilities). This characterizes corpora; it does not replace concept extraction.

Usage:
    python -m slpe.cli.weighted_fields [--config config/default.yaml]
                                       [--fields 17 31 27] [--n 500]
"""

from __future__ import annotations

import argparse
import logging
from collections import defaultdict

from slpe.characterization.weighting import aggregate_field_distribution
from slpe.config import CorpusConfig, load_config
from slpe.logging_utils import configure_logging
from slpe.manifest import RunManifest
from slpe.openalex.client import OpenAlexClient

_SELECT = "id,primary_topic,topics"


def _sample_works(client, field_id, corpus_filter, n, seed):
    per_page = min(n, 200)
    n_pages = (n + per_page - 1) // per_page
    out = []
    for page in range(1, n_pages + 1):
        payload = client.get("works", {
            "filter": f"primary_topic.field.id:{field_id},{corpus_filter}",
            "sample": n, "seed": seed, "per-page": per_page, "page": page, "select": _SELECT,
        })
        results = payload.get("results", [])
        out.extend(results)
        if len(results) < per_page:
            break
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Primary vs weighted field attribution.")
    parser.add_argument("--config", default="config/default.yaml")
    parser.add_argument("--fields", type=int, nargs="*", default=None)
    parser.add_argument("--n", type=int, default=500)
    parser.add_argument("--all", action="store_true", help="sample all 26 fields.")
    args = parser.parse_args(argv)

    import pandas as pd

    cfg = load_config(args.config)
    cfg.paths.ensure()
    configure_logging(cfg.paths.logs / "weighted_fields.log")
    log = logging.getLogger("slpe.cli")

    if args.all:
        fields = None  # resolved from the live field list below
    else:
        fields = args.fields or list(cfg.characterization.candidate_field_ids)

    en_abs = "has_abstract:true,language:en" if cfg.corpus.require_english_abstract else "has_abstract:true"
    corpus_filter = (
        f"type:{CorpusConfig.types_filter(cfg.corpus.types)},{en_abs},"
        f"from_publication_date:{cfg.characterization.year_min}-01-01,"
        f"to_publication_date:{cfg.characterization.year_max}-12-31"
    )

    manifest = RunManifest(run_name="weighted_field_attribution",
                           params={"n_per_field": args.n, "corpus_filter": corpus_filter,
                                   "seed": cfg.seed})

    rows = []
    with OpenAlexClient.from_config(cfg.openalex) as client:
        if fields is None:
            field_objs = client.list_all("fields", per_page=200, select="id,display_name")
            fields = [int(str(f["id"]).rstrip("/").split("/")[-1]) for f in field_objs]
        name_by_id = {}
        for f in client.list_all("fields", per_page=200, select="id,display_name"):
            name_by_id[int(str(f["id"]).rstrip("/").split("/")[-1])] = f["display_name"]

        for fid in fields:
            works = _sample_works(client, fid, corpus_filter, args.n, cfg.seed)
            attr = aggregate_field_distribution(works)
            # Top secondary fields (weighted mass to OTHER fields).
            other = defaultdict(float)
            for ofid, mass in attr.weighted_counts.items():
                if ofid != fid:
                    other[ofid] += mass
            top_other = sorted(other.items(), key=lambda kv: kv[1], reverse=True)[:3]
            top_str = "; ".join(
                f"{name_by_id.get(ofid, ofid)}({ofid}):{mass / attr.n_works:.2f}"
                for ofid, mass in top_other
            ) if attr.n_works else ""
            rows.append({
                "field_id": fid,
                "display_name": name_by_id.get(fid, str(fid)),
                "n_sampled": attr.n_works,
                "pct_multidisciplinary": attr.n_multidisciplinary / attr.n_works if attr.n_works else 0.0,
                "primary_share_self": attr.primary_share(fid),
                "weighted_share_self": attr.weighted_share(fid),
                "top_secondary_fields": top_str,
            })
            log.info("field %d (%s): multidisc=%.2f weighted_self=%.2f top=%s",
                     fid, name_by_id.get(fid, fid),
                     rows[-1]["pct_multidisciplinary"], rows[-1]["weighted_share_self"], top_str)
        manifest.stats = client.stats.as_dict()

    df = pd.DataFrame(rows)
    out = cfg.paths.results / "weighted_field_attribution.csv"
    df.to_csv(out, index=False)
    manifest.hash_artifacts({"weighted_field_attribution.csv": out})
    manifest.write(cfg.paths.results / "weighted_field_attribution.manifest.json")

    print(f"\nWeighted field attribution written to {out}")
    print(df.round(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
