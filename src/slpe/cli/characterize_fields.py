"""CLI: characterize the 26 OpenAlex fields, evaluate eligibility, render report.

Usage:
    slpe-characterize-fields [--config config/default.yaml] [--limit N]
                             [--corpus-sensitivity] [--no-report] [--refresh-cache]

Outputs (under ``paths.results``):
    field_characterization.parquet / .csv     one row per field, all indicators
    field_characterization_years.csv          per-field, per-year counts
    field_eligibility.csv                      semantic + bibliometric verdicts
    field_sensitivity.csv                      eligibility sensitivity per criterion
    field_corpus_sensitivity.csv               (optional) article vs +conference corpus
    legacy_eligibility_reproduction.csv        (if legacy CSV present) audit's 6-vs-14 check
    figures/*.png                              eligibility, coverage, yearly volume
    preliminary_results_stage1.md              numbers-only write-up
    field_characterization.manifest.json       params, provenance, hashes, request stats

All collection uses aggregate queries (counts + group_by). ``--limit`` restricts
the field list BEFORE any requests are issued. Logs are redacted of secrets.
"""

from __future__ import annotations

import argparse
import logging

from slpe.characterization.eligibility import (
    eligibility_to_dataframe,
    evaluate_all,
    legacy_eligibility_from_dataframe,
    sensitivity_analysis,
)
from slpe.characterization.fields import (
    characterizations_to_dataframe,
    characterize_all_fields,
    years_to_dataframe,
)
from slpe.characterization.report import build_report_from_frames
from slpe.config import load_config, validate_temporal_protocol
from slpe.logging_utils import configure_logging
from slpe.manifest import RunManifest, file_sha256
from slpe.openalex.client import OpenAlexClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Characterize the 26 OpenAlex fields.")
    parser.add_argument("--config", default="config/default.yaml")
    parser.add_argument("--limit", type=int, default=None,
                        help="characterize only the first N fields (applied BEFORE queries).")
    parser.add_argument("--corpus-sensitivity", action="store_true",
                        help="also characterize the conference-inclusive corpus for comparison.")
    parser.add_argument("--no-report", action="store_true")
    parser.add_argument("--refresh-cache", action="store_true",
                        help="bypass cached responses and refetch.")
    parser.add_argument("--no-progress", action="store_true")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    cfg.paths.ensure()
    configure_logging(cfg.paths.logs / "characterize_fields.log")
    log = logging.getLogger("slpe.cli")

    if args.refresh_cache:
        object.__setattr__(cfg.openalex, "refresh_cache", True)

    for v in validate_temporal_protocol(cfg.temporal):
        log.warning("temporal protocol advisory: %s", v)
    if not cfg.openalex.mailto and not cfg.openalex.api_key:
        log.warning("No OPENALEX_MAILTO/OPENALEX_API_KEY set — using the common pool (slower).")

    results_dir = cfg.paths.results
    candidates = set(cfg.characterization.candidate_field_ids)

    manifest = RunManifest(
        run_name="field_characterization",
        params={
            "config_path": str(args.config),
            "year_range": [cfg.characterization.year_min, cfg.characterization.year_max],
            "corpus_types": list(cfg.corpus.types),
            "candidate_field_ids": sorted(candidates),
            "eligibility": vars(cfg.characterization.eligibility),
            "cuts": [vars(c) for c in cfg.temporal.cuts],
            "limit": args.limit,
        },
        config_sha256=file_sha256(args.config),
    )

    with OpenAlexClient.from_config(cfg.openalex) as client:
        try:
            records = characterize_all_fields(
                client, cfg.characterization, cfg.temporal, cfg.corpus,
                limit=args.limit, progress=not args.no_progress,
            )
        except Exception as exc:
            manifest.errors.append(repr(exc))
            manifest.stats = client.stats.as_dict()
            manifest.write(results_dir / "field_characterization.manifest.json")
            log.error("characterization failed: %r", exc)
            raise

        df = characterizations_to_dataframe(records)
        years_df = years_to_dataframe(records)
        elig = evaluate_all(records, cfg.characterization.eligibility)
        elig_df = eligibility_to_dataframe(elig)
        sens_df = sensitivity_analysis(records, cfg.characterization.eligibility)

        # Optional corpus sensitivity: conference-inclusive vs primary corpus.
        corpus_sens_df = None
        if args.corpus_sensitivity:
            from dataclasses import replace

            alt_corpus = replace(cfg.corpus, types=cfg.corpus.sensitivity_types)
            alt_records = characterize_all_fields(
                client, cfg.characterization, cfg.temporal, alt_corpus,
                limit=args.limit, progress=not args.no_progress,
            )
            import pandas as pd

            alt = {r.field_id: r for r in alt_records}
            corpus_sens_df = pd.DataFrame([
                {
                    "field_id": r.field_id,
                    "display_name": r.display_name,
                    "primary_corpus_semantic": r.semantic_in_range,
                    "sensitivity_corpus_semantic": alt[r.field_id].semantic_in_range,
                    "ratio": (alt[r.field_id].semantic_in_range / r.semantic_in_range)
                    if r.semantic_in_range else float("nan"),
                }
                for r in records if r.field_id in alt
            ])

        # Write artifacts.
        df.to_parquet(results_dir / "field_characterization.parquet", index=False)
        df.to_csv(results_dir / "field_characterization.csv", index=False)
        years_df.to_csv(results_dir / "field_characterization_years.csv", index=False)
        elig_df.to_csv(results_dir / "field_eligibility.csv", index=False)
        sens_df.to_csv(results_dir / "field_sensitivity.csv", index=False)
        if corpus_sens_df is not None:
            corpus_sens_df.to_csv(results_dir / "field_corpus_sensitivity.csv", index=False)

        # Legacy reproduction from preserved original CSV (if present).
        legacy_df = None
        legacy_src = results_dir / "legacy" / "field_characterization.csv"
        if legacy_src.exists():
            import pandas as pd

            orig = pd.read_csv(legacy_src)
            try:
                with_gate = legacy_eligibility_from_dataframe(orig, apply_subfield_gate=True)
                without_gate = legacy_eligibility_from_dataframe(orig, apply_subfield_gate=False)
                legacy_df = with_gate.rename(columns={"legacy_eligible": "legacy_eligible"})
                legacy_df["legacy_eligible_no_subfield_gate"] = without_gate["legacy_eligible"]
                legacy_df.to_csv(results_dir / "legacy_eligibility_reproduction.csv", index=False)
                log.info("legacy reproduction: %d eligible with gate, %d without",
                         int(with_gate["legacy_eligible"].sum()),
                         int(without_gate["legacy_eligible"].sum()))
            except KeyError as exc:
                log.warning("legacy reproduction skipped: %s", exc)

        manifest.stats = client.stats.as_dict()
        manifest.params["n_fields"] = len(records)
        manifest.params["n_semantic_eligible"] = int(sum(e.semantic_eligible for e in elig))
        manifest.params["n_bibliometric_ready"] = int(sum(e.bibliometric_ready for e in elig))

        provenance = {
            "run_utc": manifest.run_utc,
            "corpus_types": ",".join(cfg.corpus.types),
            "git_commit": manifest.git_commit or "n/a",
        }
        if not args.no_report:
            build_report_from_frames(
                df, years_df, elig_df, sens_df, legacy_df, candidates,
                results_dir, provenance=provenance,
            )

        # Hash the artifacts into the manifest.
        manifest.hash_artifacts({
            "field_characterization.csv": results_dir / "field_characterization.csv",
            "field_characterization_years.csv": results_dir / "field_characterization_years.csv",
            "field_eligibility.csv": results_dir / "field_eligibility.csv",
            "field_sensitivity.csv": results_dir / "field_sensitivity.csv",
        })
        manifest.write(results_dir / "field_characterization.manifest.json")

    n_sem = sum(e.semantic_eligible for e in elig)
    log.info("done: %d fields, %d semantic-eligible. stats=%s",
             len(records), n_sem, client.stats.as_dict())
    print(f"\nCharacterized {len(records)} fields; {n_sem} semantic-eligible.")
    print(f"Results in {results_dir}")
    cols = ["field_id", "display_name", "domain", "min_semantic_eligible_per_cut",
            "english_abstract_fraction", "with_references_fraction",
            "subfield_count", "subfield_entropy"]
    print(df.sort_values("min_semantic_eligible_per_cut", ascending=False)[cols].head(10).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
