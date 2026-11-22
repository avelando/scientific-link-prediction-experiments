"""Tests for Stage-2 collection: schema, dedup, semantic corpus, bibliometric, temporal, io."""

import pandas as pd

from slpe.collection.bibliometric import citation_edges, edge_stats
from slpe.collection.dedup import (
    apply_canonical_mapping,
    canonical_mapping,
    deduplicate,
    normalize_title,
)
from slpe.collection.io_parquet import (
    check_publications_integrity,
    dataset_count,
    read_dataset,
    write_batch,
)
from slpe.collection.schema import PUBLICATIONS_SCHEMA, normalize_work
from slpe.collection.semantic_corpus import build_semantic_corpus
from slpe.collection.temporal import assert_no_leakage, partition_by_cut
from slpe.config import TemporalConfig, TemporalCut

# --- schema ---------------------------------------------------------------

def test_short_id_and_doi_normalization():
    work = {
        "id": "https://openalex.org/W42",
        "doi": "https://doi.org/10.1/ABC",
        "title": "T",
        "abstract_inverted_index": {"hello": [0], "world": [1]},
        "publication_year": 2018, "publication_date": "2018-03-01",
        "type": "article", "language": "en",
        "primary_topic": {"id": "https://openalex.org/T5",
                          "field": {"id": "https://openalex.org/fields/17"}},
        "topics": [{"id": "https://openalex.org/T5",
                    "field": {"id": "fields/17"}, "subfield": {"id": "subfields/1702"},
                    "score": 0.9}],
        "referenced_works": ["https://openalex.org/W1", "https://openalex.org/W2"],
        "referenced_works_count": 2,
    }
    nw = normalize_work(work)
    assert nw.publication["work_id"] == "W42"
    assert nw.publication["doi"] == "10.1/abc"
    assert nw.publication["abstract"] == "hello world"
    assert nw.publication["primary_field_id"] == 17
    assert nw.publication["n_references_present"] == 2
    assert nw.topics[0]["is_primary"] is True
    assert {r["cited_id"] for r in nw.references} == {"W1", "W2"}


# --- io_parquet -----------------------------------------------------------

def test_write_and_read_batches(tmp_path):
    recs = [{"work_id": "W1", "publication_year": 2018, "publication_date": "2018-01-01"},
            {"work_id": "W2", "publication_year": 2019, "publication_date": "2019-01-01"}]
    write_batch(recs, PUBLICATIONS_SCHEMA, tmp_path, 0)
    write_batch([{"work_id": "W3", "publication_year": 2020}], PUBLICATIONS_SCHEMA, tmp_path, 1)
    assert dataset_count(tmp_path) == 3
    table = read_dataset(tmp_path, columns=["work_id"])
    assert set(table.column("work_id").to_pylist()) == {"W1", "W2", "W3"}


def test_integrity_detects_year_date_mismatch(tmp_path):
    recs = [{"work_id": "W1", "publication_year": 2018, "publication_date": "2019-01-01"}]
    write_batch(recs, PUBLICATIONS_SCHEMA, tmp_path, 0)
    issues = check_publications_integrity(read_dataset(tmp_path))
    assert any("mismatch" in i for i in issues)


# --- dedup ----------------------------------------------------------------

def _pub(wid, doi=None, title="T", year=2018, date="2018-01-01", abstract="a b c"):
    tokens = len(abstract.split()) if abstract else 0
    return {"work_id": wid, "doi": doi, "title": title, "abstract": abstract,
            "abstract_tokens": tokens, "publication_year": year, "publication_date": date,
            "type": "article", "language": "en"}


def test_dedup_exact_and_doi_version_link():
    df = pd.DataFrame([
        _pub("W1", doi="10.1/x", date="2019-01-01"),
        _pub("W2", doi="10.1/x", date="2018-01-01"),   # earlier -> canonical
        _pub("W1", doi="10.1/x", date="2019-01-01"),   # exact dup of W1
        _pub("W3", doi="10.2/y"),
    ])
    canonical, links = deduplicate(df)
    ids = set(canonical["work_id"])
    assert "W2" in ids and "W3" in ids       # W2 canonical for the DOI group
    assert "W1" not in ids                     # linked/removed as a version
    assert (links["rule"] == "same_doi").any()
    assert (links["rule"] == "same_work_id").any()


def test_dedup_uncertain_title_not_merged():
    df = pd.DataFrame([
        _pub("W1", doi="10.1/a", title="A Great Study"),
        _pub("W2", doi="10.2/b", title="A Great Study!"),  # same title, diff DOI
    ])
    canonical, links = deduplicate(df)
    assert len(canonical) == 2  # NOT merged
    assert (links["confidence"] == "uncertain").any()


def test_normalize_title():
    assert normalize_title("A, Great: Study!") == "a great study"
    assert normalize_title(None) is None


def test_canonical_mapping_applied_to_references():
    df = pd.DataFrame([
        _pub("W1", doi="10.1/x", date="2019-01-01"),
        _pub("W2", doi="10.1/x", date="2018-01-01"),  # canonical
    ])
    _, links = deduplicate(df)
    mapping = canonical_mapping(links)
    assert mapping == {"W1": "W2"}  # confirmed link only
    refs = pd.DataFrame([{"citing_id": "W1", "cited_id": "W9"},
                         {"citing_id": "W5", "cited_id": "W1"}])
    remapped = apply_canonical_mapping(refs, mapping, ["citing_id", "cited_id"])
    assert remapped.iloc[0]["citing_id"] == "W2"  # W1 -> canonical W2
    assert remapped.iloc[1]["cited_id"] == "W2"
    assert remapped.iloc[1]["citing_id"] == "W5"  # unmapped left as-is


# --- semantic corpus ------------------------------------------------------

def test_semantic_corpus_exclusions():
    df = pd.DataFrame([
        _pub("W1", abstract="w " * 30, title="ok"),                 # included
        {**_pub("W2"), "abstract": None, "abstract_tokens": 0},     # no_abstract
        {**_pub("W3"), "abstract": "short", "abstract_tokens": 1},  # short_abstract
        {**_pub("W4"), "title": "", "abstract_tokens": 30},         # no_title
        {**_pub("W5"), "language": "fr", "abstract_tokens": 30},    # not_english
    ])
    corpus, stats = build_semantic_corpus(df, min_tokens=20)
    assert stats.n_input == 5
    assert "W1" in set(corpus["work_id"])
    assert stats.exclusions.get("no_abstract") == 1
    assert stats.exclusions.get("short_abstract") == 1
    assert stats.exclusions.get("no_title") == 1
    assert stats.exclusions.get("not_english") == 1


# --- bibliometric ---------------------------------------------------------

def test_citation_edges_and_stats():
    refs = pd.DataFrame([
        {"citing_id": "W1", "cited_id": "W2"},
        {"citing_id": "W1", "cited_id": "W2"},   # duplicate edge
        {"citing_id": "W1", "cited_id": "W1"},   # self -> dropped
        {"citing_id": "W2", "cited_id": "WX"},   # external target
    ])
    edges = citation_edges(refs)
    assert len(edges) == 2  # dedup + self-citation removed
    stats = edge_stats(edges, corpus_ids={"W1", "W2"})
    assert stats.n_cited_in_corpus == 1 and stats.n_cited_outside_corpus == 1


# --- temporal -------------------------------------------------------------

def test_partition_by_cut_and_leakage():
    temporal = TemporalConfig(5, 1, 3, cuts=(TemporalCut("c", 2013, 2017, 2018),),
                              full_history_start=2000)
    cut = temporal.cuts[0]
    df = pd.DataFrame([
        {"work_id": "W1", "publication_year": 2015},  # predictor
        {"work_id": "W2", "publication_year": 2017},  # predictor (== T)
        {"work_id": "W3", "publication_year": 2018},  # emergence (T+1)
        {"work_id": "W4", "publication_year": 2020},  # future_other
    ])
    part = partition_by_cut(df, temporal, cut)
    assert set(part.predictor["work_id"]) == {"W1", "W2"}
    assert set(part.emergence["work_id"]) == {"W3"}
    assert set(part.future_other["work_id"]) == {"W4"}
    assert assert_no_leakage(part.predictor, cut) == []
    # A leaked predictor row is detected.
    leaked = pd.DataFrame([{"work_id": "X", "publication_year": 2019}])
    assert assert_no_leakage(leaked, cut)
