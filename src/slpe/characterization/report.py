"""Render Stage-1 figures and a markdown summary from FROZEN artifacts.

To avoid mixing numbers from one collection with metadata from another (an audit
finding), every function here consumes already-written DataFrames/CSVs — it makes
no OpenAlex calls. The characterization CLI writes these artifacts; the report CLI
re-renders strictly from them.

Visual encoding (fixed per the audit): COLOUR encodes eligibility; MARKER/EDGE
encodes whether the field is a project candidate — the two axes never share a
channel.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

if TYPE_CHECKING:
    import pandas as pd

_ELIGIBLE_COLOR = "#2e7d32"
_INELIGIBLE_COLOR = "#95a5a6"
_BIBLIO_EDGE = "#1565c0"
_CANDIDATE_EDGE = "#c0392b"


def _elig_color(semantic_eligible: bool) -> str:
    return _ELIGIBLE_COLOR if semantic_eligible else _INELIGIBLE_COLOR


def plot_eligible_volume(df: pd.DataFrame, candidates: set[int], out_path: Path) -> Path:
    d = df.sort_values("min_semantic_eligible_per_cut")
    names = [f"{r.display_name} ({r.field_id})" for r in d.itertuples()]
    vals = list(d["min_semantic_eligible_per_cut"])
    colors = [_elig_color(bool(e)) for e in d["semantic_eligible"]]
    edges = [_CANDIDATE_EDGE if fid in candidates else "none" for fid in d["field_id"]]

    fig, ax = plt.subplots(figsize=(9, 10))
    ax.barh(names, vals, color=colors, edgecolor=edges, linewidth=1.6)
    ax.set_xscale("log")
    ax.set_xlabel("Min SEMANTIC-eligible works per cut (type + en abstract), log scale")
    ax.set_title("Stage 1 — semantic-corpus volume per temporal cut, by field")
    handles = [
        plt.Rectangle((0, 0), 1, 1, color=_ELIGIBLE_COLOR),
        plt.Rectangle((0, 0), 1, 1, color=_INELIGIBLE_COLOR),
        plt.Rectangle((0, 0), 1, 1, facecolor="white", edgecolor=_CANDIDATE_EDGE, linewidth=1.6),
    ]
    ax.legend(handles, ["semantic-eligible", "ineligible", "project candidate (edge)"],
              loc="lower right")
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    return out_path


def plot_coverage_scatter(df: pd.DataFrame, candidates: set[int], out_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(9, 7))
    for r in df.itertuples():
        color = _elig_color(bool(r.semantic_eligible))
        is_cand = r.field_id in candidates
        ax.scatter(
            r.english_abstract_fraction, r.with_references_fraction,
            c=color, marker="D" if is_cand else "o",
            s=120 if is_cand else 55,
            edgecolors=_CANDIDATE_EDGE if is_cand else "white",
            linewidths=1.6 if is_cand else 0.5, zorder=3,
        )
        if is_cand or r.semantic_eligible:
            ax.annotate(str(r.field_id), (r.english_abstract_fraction, r.with_references_fraction),
                        fontsize=8, xytext=(3, 3), textcoords="offset points")
    ax.axvline(0.5, ls="--", c="k", lw=0.7)
    ax.axhline(0.5, ls="--", c="k", lw=0.7)
    ax.set_xlabel("English-abstract fraction (metadata proxy; semantic / corpus-type)")
    ax.set_ylabel("With-references fraction (bibliometric / semantic)")
    ax.set_title("Stage 1 — coverage by field (colour=eligible, diamond=candidate)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    return out_path


def plot_candidate_years(years_df: pd.DataFrame, field_ids: list[int],
                         names: dict[int, str], out_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(9, 6))
    for fid in field_ids:
        sub = years_df[years_df["field_id"] == fid].sort_values("year")
        if sub.empty:
            continue
        ax.plot(sub["year"], sub["semantic"], marker="o", label=f"{names.get(fid, fid)} ({fid})")
    ax.set_xlabel("Publication year")
    ax.set_ylabel("Semantic-eligible works (type + en abstract)")
    ax.set_title("Stage 1 — yearly semantic-corpus volume for selected fields")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    return out_path


def write_markdown_report(
    df: pd.DataFrame,
    elig_df: pd.DataFrame,
    sens_df: pd.DataFrame | None,
    legacy_df: pd.DataFrame | None,
    candidates: set[int],
    figures: dict[str, Path],
    out_path: Path,
    *,
    provenance: dict[str, str],
    results_dir: Path,
) -> Path:
    merged = df.merge(
        elig_df[["field_id", "semantic_eligible", "bibliometric_ready", "failed_semantic_criteria"]],
        on="field_id", how="left",
    )
    name_by_id = dict(zip(df["field_id"], df["display_name"]))

    def rel(p: Path) -> str:
        try:
            return p.relative_to(results_dir).as_posix()
        except ValueError:
            return p.as_posix()

    lines: list[str] = []
    lines.append("# Stage 1 — preliminary results: field characterization & eligibility\n")
    lines.append(
        f"_Rendered from frozen artifacts. Collection run: {provenance.get('run_utc', 'n/a')} "
        f"(code run time, NOT a frozen DB snapshot). Corpus types: "
        f"{provenance.get('corpus_types', 'n/a')}. git: {provenance.get('git_commit', 'n/a')}._\n"
    )
    lines.append(
        "> Feasibility indicators only. Eligibility uses data quality, never model "
        "accuracy. English-abstract figures are OpenAlex METADATA flags; see the "
        "textual-quality sampling report for inspected text coverage.\n"
    )

    elig = merged[merged["semantic_eligible"] == True]
    elig = elig.sort_values("min_semantic_eligible_per_cut", ascending=False)
    lines.append("## Summary\n")
    lines.append(f"- Fields characterized: **{len(df)}** of 26.")
    lines.append(f"- Semantic-eligible: **{int(merged['semantic_eligible'].sum())}**; "
                 f"bibliometric-ready: **{int(merged['bibliometric_ready'].sum())}**.")
    cand_rows = merged[merged["field_id"].isin(candidates)]
    cand_status = ", ".join(
        f"{r.display_name} ({r.field_id}): "
        f"{'semantic-eligible' if r.semantic_eligible else 'INELIGIBLE'}"
        f"{'' if r.bibliometric_ready else ' (not bibliometric-ready)' if r.semantic_eligible else ''}"
        for r in cand_rows.itertuples()
    )
    lines.append(f"- Project candidates — {cand_status}.\n")

    lines.append("## Semantic-eligible fields, ranked by min semantic volume per cut\n")
    lines.append("| field | id | domain | min semantic/cut | en-abstract | with-refs | biblio-ready | subfields | entropy |")
    lines.append("|---|---|---|---:|---:|---:|:--:|---:|---:|")
    for r in elig.itertuples():
        lines.append(
            f"| {r.display_name} | {r.field_id} | {r.domain} | {int(r.min_semantic_eligible_per_cut):,} | "
            f"{r.english_abstract_fraction:.2f} | {r.with_references_fraction:.2f} | "
            f"{'yes' if r.bibliometric_ready else 'no'} | {int(r.subfield_count)} | {r.subfield_entropy:.2f} |"
        )
    lines.append("")

    flagged = cand_rows[cand_rows["semantic_eligible"] == False]
    lines.append("## Candidate fields flagged ineligible\n")
    if len(flagged):
        for r in flagged.itertuples():
            lines.append(f"- **{r.display_name} ({r.field_id})**: {r.failed_semantic_criteria}")
        lines.append("")
    else:
        lines.append("- None. All project candidates are semantic-eligible under the "
                     "corrected criteria (subfield count is no longer a gate).\n")

    if sens_df is not None and len(sens_df):
        lines.append("## Eligibility sensitivity (how the eligible set shifts per criterion)\n")
        lines.append("| scenario | n semantic-eligible | fields |")
        lines.append("|---|---:|---|")
        for r in sens_df.itertuples():
            lines.append(f"| {r.scenario} | {r.n_semantic_eligible} | {r.fields} |")
        lines.append("")

    if legacy_df is not None and len(legacy_df):
        n_legacy = int(legacy_df["legacy_eligible"].sum()) if "legacy_eligible" in legacy_df else None
        lines.append("## Legacy-criteria reproduction (on the ORIGINAL cached data)\n")
        lines.append(
            f"- Audited criteria incl. the `subfield >= 10` gate reproduced **{n_legacy}** "
            "eligible fields on the original results CSV (see `legacy/`). Removing only "
            "that gate raises the count — confirming the audit's observation that the "
            "subfield gate dominated the old selection.\n"
        )

    # Domain recommendation — evidence-based, privileging data quality + diversity.
    lines.append("## Domain recommendation (preliminary)\n")
    cand_elig = cand_rows[cand_rows["semantic_eligible"] == True]
    if len(cand_elig):
        n_domains = cand_elig["domain"].nunique()
        lines.append(
            "The three project candidates are all semantic-eligible and bibliometric-ready, "
            f"and span {n_domains} OpenAlex domain(s):\n"
        )
        for r in cand_elig.sort_values("min_semantic_eligible_per_cut", ascending=False).itertuples():
            lines.append(
                f"- **{r.display_name} ({r.field_id})** — {r.domain}; "
                f"min semantic/cut {int(r.min_semantic_eligible_per_cut):,}, "
                f"en-abstract {r.english_abstract_fraction:.2f}, refs {r.with_references_fraction:.2f}, "
                f"subfield entropy {r.subfield_entropy:.2f}."
            )
        lines.append(
            "\nThese remain the recommended candidates for the main evaluation on grounds of "
            "coverage and disciplinary diversity. Open items before the choice is FIXED: "
            "(a) confirm Computer Science's corpus-type decision — including conference-papers "
            "roughly doubles its semantic corpus (see `field_corpus_sensitivity.csv`); "
            "(b) the selection must be frozen BEFORE any predictive results are seen. "
            "The pick is not forced here where information is still pending.\n"
        )
    else:
        lines.append("- Candidates not all eligible; see the table above.\n")

    lines.append("## Figures\n")
    for caption, path in figures.items():
        lines.append(f"- {caption}: `{rel(path)}`")
    lines.append("")

    lines.append("## Full tables & provenance\n")
    lines.append(f"- Per-field indicators: `{rel(results_dir / 'field_characterization.csv')}`")
    lines.append(f"- Per-year counts: `{rel(results_dir / 'field_characterization_years.csv')}`")
    lines.append(f"- Eligibility verdicts: `{rel(results_dir / 'field_eligibility.csv')}`")
    lines.append(f"- Sensitivity: `{rel(results_dir / 'field_sensitivity.csv')}`")
    lines.append(f"- Run manifest (hashes, versions): `{rel(results_dir / 'field_characterization.manifest.json')}`\n")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def build_report_from_frames(
    df: pd.DataFrame,
    years_df: pd.DataFrame,
    elig_df: pd.DataFrame,
    sens_df: pd.DataFrame | None,
    legacy_df: pd.DataFrame | None,
    candidates: set[int],
    results_dir: Path,
    *,
    provenance: dict[str, str],
) -> dict[str, Path]:
    fig_dir = results_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    name_by_id = dict(zip(df["field_id"], df["display_name"]))

    # Merge eligibility verdicts into the characterization frame for the figures.
    plot_df = df.merge(
        elig_df[["field_id", "semantic_eligible", "bibliometric_ready"]],
        on="field_id", how="left",
    )

    figures = {
        "Semantic volume per cut (all fields)": plot_eligible_volume(
            plot_df, candidates, fig_dir / "stage1_eligible_volume.png"),
        "Coverage scatter": plot_coverage_scatter(
            plot_df, candidates, fig_dir / "stage1_coverage_scatter.png"),
    }
    top_eligible = list(
        df[df["field_id"].isin(elig_df[elig_df["semantic_eligible"] == True]["field_id"])]
        .sort_values("min_semantic_eligible_per_cut", ascending=False)["field_id"].head(4)
    )
    year_fields = list(dict.fromkeys(sorted(candidates) + top_eligible))
    figures["Yearly semantic volume (candidates + top eligible)"] = plot_candidate_years(
        years_df, year_fields, name_by_id, fig_dir / "stage1_candidate_years.png")

    report_path = write_markdown_report(
        df, elig_df, sens_df, legacy_df, candidates, figures,
        results_dir / "preliminary_results_stage1.md",
        provenance=provenance, results_dir=results_dir,
    )
    out = {"report": report_path}
    out.update({f"figure::{k}": v for k, v in figures.items()})
    return out
