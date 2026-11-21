"""Turn the Stage-1 characterization into analysable tables, figures and a report.

Consumes the artifacts written by ``slpe.cli.characterize_fields`` (the per-field
characterization and eligibility tables) plus the record objects, and produces:

    * figures/stage1_eligible_volume.png   — eligible volume per cut, all 26 fields
    * figures/stage1_coverage_scatter.png  — English-abstract vs reference coverage
    * figures/stage1_candidate_years.png   — yearly eligible volume for key fields
    * preliminary_results_stage1.md        — a concise, numbers-only write-up

Everything is derived from *measured* indicators; the report states only what was
computed and never claims predictive validation.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import matplotlib

matplotlib.use("Agg")  # headless, deterministic rendering
import matplotlib.pyplot as plt  # noqa: E402

from slpe.characterization.eligibility import EligibilityResult  # noqa: E402
from slpe.characterization.fields import FieldCharacterization  # noqa: E402

if TYPE_CHECKING:
    import pandas as pd

_CANDIDATE_COLOR = "#c0392b"
_ELIGIBLE_COLOR = "#2e7d32"
_INELIGIBLE_COLOR = "#95a5a6"


def _bar_colors(
    records: list[FieldCharacterization],
    elig_by_id: dict[int, bool],
    candidates: set[int],
) -> list[str]:
    colors = []
    for r in records:
        if r.field_id in candidates:
            colors.append(_CANDIDATE_COLOR)
        elif elig_by_id.get(r.field_id):
            colors.append(_ELIGIBLE_COLOR)
        else:
            colors.append(_INELIGIBLE_COLOR)
    return colors


def plot_eligible_volume(
    records: list[FieldCharacterization],
    elig_by_id: dict[int, bool],
    candidates: set[int],
    out_path: Path,
) -> Path:
    recs = sorted(records, key=lambda r: r.min_eligible_per_cut)
    names = [f"{r.display_name} ({r.field_id})" for r in recs]
    vals = [r.min_eligible_per_cut for r in recs]
    colors = _bar_colors(recs, elig_by_id, candidates)

    fig, ax = plt.subplots(figsize=(9, 10))
    ax.barh(names, vals, color=colors)
    ax.set_xscale("log")
    ax.set_xlabel("Min eligible works per cut (en abstract + references), log scale")
    ax.set_title("Stage 1 — eligible volume per temporal cut, by OpenAlex field")
    handles = [
        plt.Rectangle((0, 0), 1, 1, color=_CANDIDATE_COLOR),
        plt.Rectangle((0, 0), 1, 1, color=_ELIGIBLE_COLOR),
        plt.Rectangle((0, 0), 1, 1, color=_INELIGIBLE_COLOR),
    ]
    ax.legend(handles, ["project candidate", "eligible", "ineligible"], loc="lower right")
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    return out_path


def plot_coverage_scatter(
    records: list[FieldCharacterization],
    elig_by_id: dict[int, bool],
    candidates: set[int],
    out_path: Path,
) -> Path:
    fig, ax = plt.subplots(figsize=(9, 7))
    for r in records:
        if r.field_id in candidates:
            color, marker, size = _CANDIDATE_COLOR, "D", 90
        elif elig_by_id.get(r.field_id):
            color, marker, size = _ELIGIBLE_COLOR, "o", 60
        else:
            color, marker, size = _INELIGIBLE_COLOR, "o", 40
        ax.scatter(r.english_abstract_fraction, r.with_references_fraction,
                   c=color, marker=marker, s=size, edgecolors="white", linewidths=0.5, zorder=3)
        if r.field_id in candidates or elig_by_id.get(r.field_id):
            ax.annotate(str(r.field_id), (r.english_abstract_fraction, r.with_references_fraction),
                        fontsize=8, xytext=(3, 3), textcoords="offset points")
    ax.axvline(0.5, ls="--", c="k", lw=0.7)
    ax.axhline(0.5, ls="--", c="k", lw=0.7)
    ax.set_xlabel("English-abstract fraction")
    ax.set_ylabel("With-references fraction (of English-abstract works)")
    ax.set_title("Stage 1 — documentary coverage by field (labels = field id)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    return out_path


def plot_candidate_years(
    records: list[FieldCharacterization],
    field_ids: list[int],
    out_path: Path,
) -> Path:
    by_id = {r.field_id: r for r in records}
    fig, ax = plt.subplots(figsize=(9, 6))
    for fid in field_ids:
        r = by_id.get(fid)
        if r is None:
            continue
        xs = [y.year for y in r.years]
        ys = [y.eligible for y in r.years]
        ax.plot(xs, ys, marker="o", label=f"{r.display_name} ({fid})")
    ax.set_xlabel("Publication year")
    ax.set_ylabel("Eligible works (en abstract + references)")
    ax.set_title("Stage 1 — yearly eligible volume for selected fields")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    return out_path


def write_markdown_report(
    records: list[FieldCharacterization],
    elig: list[EligibilityResult],
    candidates: set[int],
    figures: dict[str, Path],
    out_path: Path,
    *,
    snapshot_utc: str,
    results_dir: Path,
) -> Path:
    by_id = {r.field_id: r for r in records}
    elig_by_id = {e.field_id: e for e in elig}
    eligible = [e for e in elig if e.eligible]
    eligible_sorted = sorted(
        eligible, key=lambda e: by_id[e.field_id].min_eligible_per_cut, reverse=True
    )

    def rel(p: Path) -> str:
        try:
            return p.relative_to(results_dir).as_posix()
        except ValueError:
            return p.as_posix()

    lines: list[str] = []
    lines.append("# Stage 1 — preliminary results: field characterization & eligibility\n")
    lines.append(
        f"_Data snapshot (UTC): {snapshot_utc}. Source: OpenAlex aggregate queries._\n"
    )
    lines.append(
        "> Feasibility indicators only. Eligibility is decided on data quality, "
        "never on model accuracy. No predictive claim is made here.\n"
    )

    lines.append("## Summary\n")
    lines.append(f"- Fields characterized: **{len(records)}** of 26.")
    lines.append(f"- Eligible under current thresholds: **{len(eligible)}**.")
    cand_status = ", ".join(
        f"{by_id[c].display_name} ({c}): "
        f"{'eligible' if elig_by_id[c].eligible else 'INELIGIBLE'}"
        for c in sorted(candidates) if c in by_id
    )
    lines.append(f"- Project candidates — {cand_status}.\n")

    lines.append("## Eligible fields, ranked by min eligible volume per cut\n")
    lines.append("| field | id | domain | min eligible/cut | en-abstract | with-refs | subfields |")
    lines.append("|---|---|---|---:|---:|---:|---:|")
    for e in eligible_sorted:
        r = by_id[e.field_id]
        lines.append(
            f"| {r.display_name} | {r.field_id} | {r.domain} | {r.min_eligible_per_cut:,} | "
            f"{r.english_abstract_fraction:.2f} | {r.with_references_fraction:.2f} | "
            f"{r.subfield_diversity} |"
        )
    lines.append("")

    lines.append("## Candidate fields flagged ineligible (criterion detail)\n")
    flagged = [c for c in sorted(candidates) if c in elig_by_id and not elig_by_id[c].eligible]
    if flagged:
        for c in flagged:
            e = elig_by_id[c]
            lines.append(f"- **{by_id[c].display_name} ({c})**: {'; '.join(e.reasons)}")
        lines.append(
            "\n> These thresholds are development placeholders (see config "
            "`characterization.eligibility`). A flagged project candidate is reported, "
            "not silently dropped; the criterion should be reviewed before the main study.\n"
        )
    else:
        lines.append("- None.\n")

    lines.append("## Figures\n")
    for caption, path in figures.items():
        lines.append(f"- {caption}: `{rel(path)}`")
    lines.append("")

    lines.append("## Full tables\n")
    lines.append(f"- Per-field indicators: `{rel(results_dir / 'field_characterization.csv')}`")
    lines.append(f"- Eligibility verdicts: `{rel(results_dir / 'field_eligibility.csv')}`")
    lines.append(f"- Run manifest: `{rel(results_dir / 'field_characterization.manifest.json')}`\n")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def build_report(
    records: list[FieldCharacterization],
    elig: list[EligibilityResult],
    candidates: set[int],
    results_dir: Path,
    *,
    snapshot_utc: str,
) -> dict[str, Path]:
    """Generate all figures + the markdown report. Returns a map of output paths."""
    fig_dir = results_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    elig_by_id = {e.field_id: e.eligible for e in elig}

    figures = {
        "Eligible volume per cut (all fields)": plot_eligible_volume(
            records, elig_by_id, candidates, fig_dir / "stage1_eligible_volume.png"
        ),
        "Documentary coverage scatter": plot_coverage_scatter(
            records, elig_by_id, candidates, fig_dir / "stage1_coverage_scatter.png"
        ),
    }
    # Candidates + top eligible fields for the yearly-volume plot.
    top_eligible = [e.field_id for e in sorted(
        (e for e in elig if e.eligible),
        key=lambda e: next(r for r in records if r.field_id == e.field_id).min_eligible_per_cut,
        reverse=True,
    )][:4]
    year_fields = list(dict.fromkeys(sorted(candidates) + top_eligible))
    figures["Yearly eligible volume (candidates + top eligible)"] = plot_candidate_years(
        records, year_fields, fig_dir / "stage1_candidate_years.png"
    )

    report_path = write_markdown_report(
        records, elig, candidates, figures,
        results_dir / "preliminary_results_stage1.md",
        snapshot_utc=snapshot_utc, results_dir=results_dir,
    )
    out = {"report": report_path}
    out.update({f"figure::{k}": v for k, v in figures.items()})
    return out
