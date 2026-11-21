"""Tests for textual-quality inspection and Wilson intervals (offline)."""

from slpe.characterization.quality_sampling import (
    inspect_work,
    sample_size_for_margin,
    summarize_inspections,
    wilson_interval,
)


def test_wilson_interval_contains_point_estimate():
    lo, hi = wilson_interval(80, 100)
    assert lo < 0.8 < hi
    assert 0.0 <= lo <= hi <= 1.0


def test_wilson_interval_zero_n():
    assert wilson_interval(0, 0) == (0.0, 0.0)


def test_sample_size_grows_as_margin_shrinks():
    assert sample_size_for_margin(0.05) < sample_size_for_margin(0.02)
    assert sample_size_for_margin(0.05) == 385  # z=1.96, p=0.5


def test_inspect_work_good_record():
    work = {
        "title": "A study of X",
        "language": "en",
        "abstract_inverted_index": {"We": [0], "study": [1], "X": [2], "and": [3],
                                     "report": [4], "many": [5], "detailed": [6],
                                     "results": [7], "here": [8], "in": [9],
                                     "full": [10], "across": [11], "several": [12],
                                     "careful": [13], "controlled": [14],
                                     "experiments": [15], "with": [16], "clear": [17],
                                     "robust": [18], "findings": [19], "throughout": [20]},
        "referenced_works": ["W1", "W2"],
        "publication_year": 2018,
        "publication_date": "2018-05-01",
    }
    insp = inspect_work(work)
    assert insp.has_title and insp.language_en and insp.abstract_reconstructable
    assert insp.has_references and insp.year_consistent
    assert insp.short_abstract is False  # 21 tokens >= 20


def test_inspect_work_detects_problems():
    work = {"title": "", "language": "fr", "abstract_inverted_index": {"court": [0]},
            "referenced_works": [], "publication_year": 2020, "publication_date": "2019-01-01"}
    insp = inspect_work(work)
    assert not insp.has_title
    assert not insp.language_en
    assert insp.short_abstract is True   # 1 token
    assert not insp.has_references
    assert not insp.year_consistent      # 2019 != 2020


def test_summarize_reports_fractions_and_cis():
    long_tokens = [f"w{i}" for i in range(30)]
    good = inspect_work({"title": "t", "language": "en",
                         "abstract_inverted_index": {w: [i] for i, w in enumerate(long_tokens)},
                         "referenced_works": ["x"], "publication_year": 2018,
                         "publication_date": "2018-01-01"})
    bad = inspect_work({"title": "", "language": "de", "abstract_inverted_index": None,
                        "referenced_works": [], "publication_year": 2018, "publication_date": None})
    rep = summarize_inspections(17, "filter", [good, bad])
    assert rep.n_sampled == 2
    assert 0.0 <= rep.frac_language_en <= 1.0
    assert "frac_language_en" in rep.ci
