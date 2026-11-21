"""CLI: characterize the 26 OpenAlex fields and evaluate eligibility.

Usage:
    slpe-characterize-fields [--config config/default.yaml] [--limit N] [--no-progress]

Outputs (under ``paths.results``):
    field_characterization.parquet   one row per field, all indicators
    field_characterization.csv       same, human-readable
    field_eligibility.csv            eligibility verdict + failed criteria
    field_characterization.manifest.json   params, snapshot date, request stats

Collection uses only aggregate OpenAlex queries (counts + group_by). Re-running is
cheap: responses are cached on disk, so a second run hits the cache.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from slpe.characterization.eligibility import eligibility_to_dataframe, evaluate_all
from slpe.characterization.fields import characterize_all_fields, characterizations_to_dataframe
from slpe.config import load_config, validate_temporal_protocol
from slpe.manifest import RunManifest
from slpe.openalex.client import OpenAlexClient


def _setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stderr),
            logging.FileHandler(log_dir / "characterize_fields.log", encoding="utf-8"),
        ],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Characterize the 26 OpenAlex fields.")
    parser.add_argument("--config", default="config/default.yaml")
    parser.add_argument("--limit", type=int, default=None,
                        help="characterize only the first N fields (smoke test).")
    parser.add_argument("--no-progress", action="store_true")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    cfg.paths.ensure()
    _setup_logging(cfg.paths.logs)
    log = logging.getLogger("slpe.cli")

    violations = validate_temporal_protocol(cfg.temporal)
    if violations:
        log.warning("temporal protocol advisories: %s", "; ".join(violations))

    if not cfg.openalex.mailto and not cfg.openalex.api_key:
        log.warning(
            "No OPENALEX_MAILTO or OPENALEX_API_KEY set — using the common pool "
            "(slower, may be rate-limited). Set OPENALEX_MAILTO for the polite pool."
        )

    manifest = RunManifest(
        run_name="field_characterization",
        params={
            "config_path": str(args.config),
            "year_min": cfg.characterization.year_min,
            "year_max": cfg.characterization.year_max,
            "candidate_field_ids": list(cfg.characterization.candidate_field_ids),
            "eligibility": vars(cfg.characterization.eligibility),
            "cuts": [vars(c) for c in cfg.temporal.cuts],
            "limit": args.limit,
        },
    )

    with OpenAlexClient.from_config(cfg.openalex) as client:
        try:
            records = characterize_all_fields(
                client, cfg.characterization, cfg.temporal, progress=not args.no_progress
            )
        except Exception as exc:  # record, then surface — never fabricate partial data
            manifest.errors.append(repr(exc))
            manifest.stats = client.stats.as_dict()
            manifest.write(cfg.paths.results / "field_characterization.manifest.json")
            log.error("characterization failed: %r", exc)
            raise

        if args.limit is not None:
            records = records[: args.limit]

        df = characterizations_to_dataframe(records)
        elig = evaluate_all(records, cfg.characterization.eligibility)
        elig_df = eligibility_to_dataframe(elig)

        results_dir = cfg.paths.results
        df.to_parquet(results_dir / "field_characterization.parquet", index=False)
        df.to_csv(results_dir / "field_characterization.csv", index=False)
        elig_df.to_csv(results_dir / "field_eligibility.csv", index=False)

        manifest.stats = client.stats.as_dict()
        manifest.params["n_fields_characterized"] = len(records)
        manifest.params["n_eligible"] = int(sum(r.eligible for r in elig))
        manifest.write(results_dir / "field_characterization.manifest.json")

    n_elig = sum(r.eligible for r in elig)
    log.info("done: %d fields characterized, %d eligible", len(records), n_elig)
    log.info("request stats: %s", client.stats.as_dict())
    print(f"\nCharacterized {len(records)} fields; {n_elig} eligible.")
    print(f"Results written to {results_dir}")
    print("Top fields by eligible volume per cut:")
    top = df.sort_values("min_eligible_per_cut", ascending=False).head(8)
    cols = ["field_id", "display_name", "domain", "min_eligible_per_cut",
            "english_abstract_fraction", "with_references_fraction", "subfield_diversity"]
    print(top[cols].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
