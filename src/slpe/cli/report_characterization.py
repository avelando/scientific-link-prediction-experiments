"""CLI: build analysable figures + a markdown summary from the Stage-1 data.

Run AFTER ``slpe-characterize-fields``. It replays the cached OpenAlex responses
(so it is fast and makes no new network calls when the cache is warm), rebuilds the
per-field records, and writes figures + ``preliminary_results_stage1.md``.

Usage:
    python -m slpe.cli.report_characterization [--config config/default.yaml]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from slpe.characterization.eligibility import evaluate_all
from slpe.characterization.fields import characterize_all_fields
from slpe.characterization.report import build_report
from slpe.config import load_config
from slpe.openalex.client import OpenAlexClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report Stage-1 characterization.")
    parser.add_argument("--config", default="config/default.yaml")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(sys.stderr)])
    log = logging.getLogger("slpe.cli")

    cfg = load_config(args.config)
    cfg.paths.ensure()

    # Prefer the snapshot timestamp recorded by the characterization run.
    manifest_path = cfg.paths.results / "field_characterization.manifest.json"
    snapshot = datetime.now(timezone.utc).isoformat()
    if manifest_path.exists():
        try:
            snapshot = json.loads(manifest_path.read_text(encoding="utf-8")).get("snapshot_utc", snapshot)
        except json.JSONDecodeError:
            pass

    with OpenAlexClient.from_config(cfg.openalex) as client:
        records = characterize_all_fields(client, cfg.characterization, cfg.temporal, progress=False)
        if client.stats.n_requests > 0:
            log.info("made %d live requests (cache was cold for some fields)", client.stats.n_requests)
        elig = evaluate_all(records, cfg.characterization.eligibility)

    candidates = set(cfg.characterization.candidate_field_ids)
    outputs = build_report(records, elig, candidates, cfg.paths.results, snapshot_utc=snapshot)

    print("\nStage-1 report generated:")
    for name, path in outputs.items():
        print(f"  {name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
