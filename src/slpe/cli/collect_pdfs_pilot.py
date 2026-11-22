"""CLI: PDF viability pilot (Phase B) — measure the real OA-PDF acquisition funnel.

For each candidate field, draws a reproducible sample of OA works and runs:
    metadata -> pdf candidate URLs -> download (limits) -> validate -> extract text.

Reports the funnel the project requires (distinct quantities, never conflated):
    eligible records, OA-eligible, with PDF URL, downloaded, valid PDF, text
    extracted — plus per-area OA availability, storage used, and a projected cost /
    storage estimate to reach a target corpus. Downloads come from free OA locations
    only; the paid content API stays off unless explicitly enabled in config.

This is a SMALL real pilot (default 15 works/field). It never starts a large run.

Usage:
    python -m slpe.cli.collect_pdfs_pilot [--config config/default.yaml]
        [--fields 17 31 27] [--n 15] [--target-per-area 33000]
"""

from __future__ import annotations

import argparse
import logging

from slpe.collection.schema import short_id
from slpe.config import CorpusConfig, load_config
from slpe.logging_utils import configure_logging
from slpe.manifest import RunManifest
from slpe.openalex.client import OpenAlexClient
from slpe.pdf import WORKS_PDF_SELECT
from slpe.pdf.download import PdfDownloader
from slpe.pdf.extract import extract_text, grobid_available
from slpe.pdf.locations import pdf_candidates


def _sample_oa_works(client, field_id, corpus_filter, n, seed):
    # Select works that ALREADY expose a direct PDF URL (has_pdf_url:true), so the
    # sample concentrates on acquirable documents (Section 2).
    per_page = min(n, 200)
    payload = client.get("works", {
        "filter": f"primary_topic.field.id:{field_id},{corpus_filter},"
                  f"open_access.is_oa:true,has_pdf_url:true",
        "sample": n, "seed": seed, "per-page": per_page, "select": WORKS_PDF_SELECT,
    })
    return payload.get("results", [])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PDF viability pilot.")
    parser.add_argument("--config", default="config/default.yaml")
    parser.add_argument("--fields", type=int, nargs="*", default=None)
    parser.add_argument("--n", type=int, default=15, help="works sampled per field.")
    parser.add_argument("--target-per-area", type=int, default=33000)
    args = parser.parse_args(argv)

    import pandas as pd

    cfg = load_config(args.config)
    cfg.paths.ensure()
    configure_logging(cfg.paths.logs / "collect_pdfs_pilot.log")
    log = logging.getLogger("slpe.cli")

    fields = args.fields or list(cfg.characterization.candidate_field_ids)
    ymin, ymax = cfg.characterization.year_min, cfg.characterization.year_max
    en_abs = "has_abstract:true,language:en" if cfg.corpus.require_english_abstract else "has_abstract:true"
    corpus_filter = (
        f"type:{CorpusConfig.types_filter(cfg.corpus.types)},{en_abs},"
        f"from_publication_date:{ymin}-01-01,to_publication_date:{ymax}-12-31"
    )

    contact = cfg.openalex.mailto
    grobid = cfg.pdf.grobid_url if grobid_available(cfg.pdf.grobid_url) else None
    log.info("GROBID %s", "available" if grobid else "not configured/unreachable (using PyMuPDF)")

    manifest = RunManifest(run_name="pdf_viability_pilot",
                           params={"fields": fields, "n_per_field": args.n,
                                   "corpus_filter": corpus_filter, "seed": cfg.seed,
                                   "allow_content_api": cfg.pdf.allow_content_api,
                                   "grobid": bool(grobid)})

    per_work_rows = []
    funnel_rows = []
    attempt_rows = []
    text_dir = cfg.paths.data_processed / "pdf_fulltext"
    text_dir.mkdir(parents=True, exist_ok=True)

    with OpenAlexClient.from_config(cfg.openalex) as client, \
            PdfDownloader.create(cfg.pdf, contact=contact) as dl:
        for fid in fields:
            eligible = client.count("works", f"primary_topic.field.id:{fid},{corpus_filter}")
            oa_eligible = client.count(
                "works", f"primary_topic.field.id:{fid},{corpus_filter},open_access.is_oa:true")
            works = _sample_oa_works(client, fid, corpus_filter, args.n, cfg.seed)

            n_with_url = n_downloaded = n_reused = n_valid = n_text = 0
            sizes = []
            for w in works:
                wid = short_id(w.get("id"))
                cands = pdf_candidates(w)
                if not cands:
                    per_work_rows.append({"field_id": fid, "work_id": wid, "stage": "no_pdf_url"})
                    continue
                n_with_url += 1
                res = dl.acquire(wid, cands)
                # Fixed-schema attempts record for EVERY candidate tried (even when
                # nothing was accepted), so failures are diagnosable (4.1/4.2).
                for a in res.attempts:
                    attempt_rows.append({
                        "field_id": fid, "work_id": wid, "url": a.url, "source": a.source,
                        "ok": a.ok, "http_status": a.http_status, "content_type": a.content_type,
                        "n_bytes": a.n_bytes, "failure_reason": a.failure_reason,
                        "sha256": a.sha256,
                    })
                if res.outcome == "downloaded":
                    n_downloaded += 1
                elif res.outcome == "reused":
                    n_reused += 1
                if not res.acquired:
                    per_work_rows.append({"field_id": fid, "work_id": wid, "stage": "not_obtained",
                                          "reason": res.failure_reason})
                    continue
                n_valid += 1
                sizes.append(res.n_text_chars)
                ext = extract_text(res.pdf_path, grobid_url=grobid)
                if ext.ok and not ext.anomalies:
                    n_text += 1
                    (text_dir / f"{wid}.txt").write_text(ext.body_text[:200000], encoding="utf-8")
                per_work_rows.append({
                    "field_id": fid, "work_id": wid, "stage": "included" if ext.ok else "extract_anomaly",
                    "license": res.license, "version": res.version, "n_pages": res.n_pages,
                    "n_text_chars": res.n_text_chars, "extract_method": ext.method,
                    "anomalies": ";".join(ext.anomalies), "sha256": res.sha256,
                })
                log.info("field %d %s: acquired (%s, %d pages)", fid, wid, res.license, res.n_pages)

            funnel_rows.append({
                "field_id": fid, "eligible_records": eligible, "oa_eligible": oa_eligible,
                "oa_availability": round(oa_eligible / eligible, 3) if eligible else 0.0,
                "sampled": len(works), "with_pdf_url": n_with_url,
                "downloaded": n_downloaded, "reused": n_reused,
                "valid_pdf": n_valid, "text_extracted": n_text,
                "pdf_url_rate": round(n_with_url / len(works), 3) if works else 0.0,
                "valid_rate": round(n_valid / len(works), 3) if works else 0.0,
                "final_rate": round(n_text / len(works), 3) if works else 0.0,
            })
        manifest.stats = client.stats.as_dict()
        manifest.stats["pdf_total_bytes"] = dl.total_bytes

    funnel = pd.DataFrame(funnel_rows)
    per_work = pd.DataFrame(per_work_rows)
    # Fixed-schema attempts table, written even when no PDF was accepted.
    attempts = pd.DataFrame(attempt_rows, columns=[
        "field_id", "work_id", "url", "source", "ok", "http_status",
        "content_type", "n_bytes", "failure_reason", "sha256"])
    funnel.to_csv(cfg.paths.results / "pdf_viability_funnel.csv", index=False)
    per_work.to_csv(cfg.paths.results / "pdf_viability_perwork.csv", index=False)
    attempts.to_csv(cfg.paths.results / "pdf_download_attempts.csv", index=False)

    # Storage/cost projection from measured bytes-per-valid-PDF.
    total_valid = int(funnel["valid_pdf"].sum()) if len(funnel) else 0
    bytes_per_pdf = (dl.total_bytes / total_valid) if total_valid else 0.0
    mean_final_rate = float(funnel["final_rate"].mean()) if len(funnel) else 0.0
    target_docs = args.target_per_area * len(fields)
    # To get `target_docs` processable docs, we must sample more given the final rate.
    est_samples_needed = int(target_docs / mean_final_rate) if mean_final_rate else None
    projection = {
        "measured_bytes_per_valid_pdf": int(bytes_per_pdf),
        "mean_final_processable_rate": round(mean_final_rate, 3),
        "target_processable_docs": target_docs,
        "estimated_pdf_storage_gb": round(target_docs * bytes_per_pdf / 1e9, 2) if bytes_per_pdf else None,
        "estimated_works_to_sample": est_samples_needed,
        "note": "rates are from a SMALL sample; treat as indicative, not population estimates",
    }
    manifest.params["funnel"] = funnel_rows
    manifest.params["projection"] = projection
    manifest.hash_artifacts({"pdf_viability_funnel.csv": cfg.paths.results / "pdf_viability_funnel.csv"})
    manifest.write(cfg.paths.results / "pdf_viability_pilot.manifest.json")

    print("\n=== PDF viability funnel ===")
    print(funnel.to_string(index=False))
    print("\n=== Projection to target (indicative) ===")
    for k, v in projection.items():
        print(f"  {k}: {v}")
    print(f"\nFull-text saved to {text_dir}; manifest: "
          f"{cfg.paths.results / 'pdf_viability_pilot.manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
