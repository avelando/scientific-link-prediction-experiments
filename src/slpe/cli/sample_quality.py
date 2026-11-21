"""CLI: validate textual quality on reproducible samples of real works.

Draws a bounded random sample per candidate field (OpenAlex ``sample`` + ``seed``),
inspects titles/abstracts/references/dates, and reports coverage with Wilson 95%
confidence intervals — distinguishing sampled estimates from exact aggregate counts.

Usage:
    python -m slpe.cli.sample_quality [--config config/default.yaml]
                                      [--fields 17 31 27] [--n 384] [--margin 0.05]
"""

from __future__ import annotations

import argparse
import logging

from slpe.characterization.quality_sampling import (
    sample_field_quality,
    sample_field_quality_by_year,
    sample_size_for_margin,
)
from slpe.config import CorpusConfig, load_config
from slpe.logging_utils import configure_logging
from slpe.manifest import RunManifest
from slpe.openalex.client import OpenAlexClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sample textual quality for candidate fields.")
    parser.add_argument("--config", default="config/default.yaml")
    parser.add_argument("--fields", type=int, nargs="*", default=None,
                        help="field ids to sample (default: config candidates).")
    parser.add_argument("--n", type=int, default=None,
                        help="sample size per field (default: from --margin).")
    parser.add_argument("--margin", type=float, default=0.05,
                        help="target margin of error used to size the sample.")
    parser.add_argument("--by-year", action="store_true",
                        help="also stratify the sample by publication year.")
    parser.add_argument("--n-per-year", type=int, default=100,
                        help="sample size per year when --by-year is set.")
    args = parser.parse_args(argv)

    import pandas as pd

    cfg = load_config(args.config)
    cfg.paths.ensure()
    configure_logging(cfg.paths.logs / "sample_quality.log")
    log = logging.getLogger("slpe.cli")

    fields = args.fields if args.fields else list(cfg.characterization.candidate_field_ids)
    n = args.n or sample_size_for_margin(args.margin)
    log.info("sampling %d works/field for fields %s (margin ~%.2f)", n, fields, args.margin)

    en_abs = "has_abstract:true,language:en" if cfg.corpus.require_english_abstract else "has_abstract:true"
    corpus_filter = (
        f"type:{CorpusConfig.types_filter(cfg.corpus.types)},{en_abs},"
        f"from_publication_date:{cfg.characterization.year_min}-01-01,"
        f"to_publication_date:{cfg.characterization.year_max}-12-31"
    )

    manifest = RunManifest(
        run_name="textual_quality_sampling",
        params={"fields": fields, "n_per_field": n, "margin": args.margin,
                "corpus_filter": corpus_filter, "seed": cfg.seed},
    )

    rows = []
    with OpenAlexClient.from_config(cfg.openalex) as client:
        for fid in fields:
            rep = sample_field_quality(client, fid, corpus_filter=corpus_filter, n=n, seed=cfg.seed)
            rows.append(rep.to_flat())
            log.info("field %d: reconstructable=%.3f en=%.3f short=%.3f refs=%.3f median_tokens=%.0f",
                     fid, rep.frac_abstract_reconstructable, rep.frac_language_en,
                     rep.frac_short_abstract, rep.frac_has_references, rep.median_tokens)
        manifest.stats = client.stats.as_dict()

    df = pd.DataFrame(rows)
    # Conditionality note stored next to the data so results are never read as
    # whole-field coverage: the sample is drawn from the English-abstract corpus.
    df.insert(0, "note", "CONDITIONAL on corpus filter (type+en+abstract); "
              "NOT coverage of all works in the field")
    out = cfg.paths.results / "textual_quality_sampling.csv"
    df.to_csv(out, index=False)
    manifest.hash_artifacts({"textual_quality_sampling.csv": out})

    if args.by_year:
        year_rows = []
        years = range(cfg.characterization.year_min, cfg.characterization.year_max + 1)
        with OpenAlexClient.from_config(cfg.openalex) as client:
            for fid in fields:
                reps = sample_field_quality_by_year(
                    client, fid, corpus_filter=corpus_filter,
                    years=years, n_per_year=args.n_per_year, seed=cfg.seed)
                for year, rep in zip(years, reps, strict=False):
                    row = rep.to_flat()
                    row["field_id"], row["year"] = fid, year
                    year_rows.append(row)
        ydf = pd.DataFrame(year_rows)
        yout = cfg.paths.results / "textual_quality_by_year.csv"
        ydf.to_csv(yout, index=False)
        manifest.hash_artifacts({"textual_quality_by_year.csv": yout})
        log.info("by-year stratification written to %s", yout)

    manifest.write(cfg.paths.results / "textual_quality_sampling.manifest.json")

    print(f"\nTextual-quality sampling written to {out}")
    show = ["field_id", "n_sampled", "frac_abstract_reconstructable",
            "frac_language_en", "frac_short_abstract", "frac_has_references", "median_tokens"]
    print(df[show].round(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
