"""CLI: re-render Stage-1 figures + markdown from FROZEN artifacts (no API calls).

Reads the CSVs written by ``slpe-characterize-fields`` and regenerates the report.
It never queries OpenAlex, so a report can never mix fresh numbers with stale
metadata. Fails clearly if the required artifacts are missing.

Usage:
    python -m slpe.cli.report_characterization [--config config/default.yaml]
"""

from __future__ import annotations

import argparse
import json
import sys

from slpe.characterization.report import build_report_from_frames
from slpe.config import load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render Stage-1 report from frozen artifacts.")
    parser.add_argument("--config", default="config/default.yaml")
    args = parser.parse_args(argv)

    import pandas as pd

    cfg = load_config(args.config)
    results_dir = cfg.paths.results
    candidates = set(cfg.characterization.candidate_field_ids)

    required = {
        "characterization": results_dir / "field_characterization.csv",
        "years": results_dir / "field_characterization_years.csv",
        "eligibility": results_dir / "field_eligibility.csv",
    }
    missing = [str(p) for p in required.values() if not p.exists()]
    if missing:
        print("ERROR: missing artifacts; run slpe-characterize-fields first:\n  "
              + "\n  ".join(missing), file=sys.stderr)
        return 1

    df = pd.read_csv(required["characterization"])
    years_df = pd.read_csv(required["years"])
    elig_df = pd.read_csv(required["eligibility"])

    sens_path = results_dir / "field_sensitivity.csv"
    sens_df = pd.read_csv(sens_path) if sens_path.exists() else None
    legacy_path = results_dir / "legacy_eligibility_reproduction.csv"
    legacy_df = pd.read_csv(legacy_path) if legacy_path.exists() else None

    provenance = {"run_utc": "n/a", "corpus_types": "n/a", "git_commit": "n/a"}
    manifest_path = results_dir / "field_characterization.manifest.json"
    if manifest_path.exists():
        try:
            m = json.loads(manifest_path.read_text(encoding="utf-8"))
            provenance = {
                "run_utc": m.get("run_utc", "n/a"),
                "corpus_types": ",".join(m.get("params", {}).get("corpus_types", [])) or "n/a",
                "git_commit": m.get("git_commit") or "n/a",
            }
        except json.JSONDecodeError:
            pass

    outputs = build_report_from_frames(
        df, years_df, elig_df, sens_df, legacy_df, candidates, results_dir, provenance=provenance
    )
    print("Report rendered from frozen artifacts:")
    for name, path in outputs.items():
        print(f"  {name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
