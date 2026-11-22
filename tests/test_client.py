"""Tests for the OpenAlex client: auth, caching, retries, pagination, accounting.

Uses httpx.MockTransport so no real network calls are made.
"""

from pathlib import Path

import httpx
import pytest

from slpe.config import OpenAlexConfig
from slpe.openalex.client import OpenAlexClient, OpenAlexError


def make_config(tmp_path: Path, **over) -> OpenAlexConfig:
    defaults = dict(
        base_url="https://api.openalex.org",
        mailto="test@example.org",
        api_key=None,
        per_page=200,
        max_retries=4,
        backoff_initial_seconds=0.0,  # no real sleeping in tests
        backoff_max_seconds=0.0,
        timeout_seconds=5.0,
        cache_dir=tmp_path / "cache",
        cache_enabled=True,
        min_interval_seconds=0.0,
    )
    defaults.update(over)
    cfg = OpenAlexConfig(**defaults)
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    return cfg


def client_with_handler(cfg: OpenAlexConfig, handler) -> OpenAlexClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    return OpenAlexClient(config=cfg, _client=http)


def test_mailto_added_to_requests(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["mailto"] = request.url.params.get("mailto")
        return httpx.Response(200, json={"meta": {"count": 5}, "results": []})

    cfg = make_config(tmp_path)
    with client_with_handler(cfg, handler) as c:
        c.get("works", {"filter": "x"})
    assert seen["mailto"] == "test@example.org"


def test_cache_hit_avoids_second_network_call(tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"meta": {"count": 42}, "results": []})

    cfg = make_config(tmp_path)
    with client_with_handler(cfg, handler) as c:
        assert c.count("works", "primary_topic.field.id:17") == 42
        assert c.count("works", "primary_topic.field.id:17") == 42  # served from cache
    assert calls["n"] == 1
    assert c.stats.n_requests == 1
    assert c.stats.n_cache_hits == 1


def test_api_key_excluded_from_cache_key(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"meta": {"count": 1}, "results": []})

    # Same query, different api_key -> must still hit the same cache entry.
    cfg1 = make_config(tmp_path, api_key="KEY_A")
    with client_with_handler(cfg1, handler) as c1:
        c1.count("works", "f:1")
    cfg2 = make_config(tmp_path, api_key="KEY_B")
    with client_with_handler(cfg2, handler) as c2:
        c2.count("works", "f:1")
    assert c2.stats.n_cache_hits == 1  # cache shared despite different key
    assert c2.stats.n_requests == 0


def test_retry_on_429_then_success(tmp_path):
    seq = iter([429, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(seq)
        if status == 429:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={})
        return httpx.Response(200, json={"meta": {"count": 7}, "results": []})

    cfg = make_config(tmp_path)
    with client_with_handler(cfg, handler) as c:
        assert c.count("works", "f:1") == 7
    assert c.stats.n_retries == 1


def test_exhausted_retries_raises_not_fabricates(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={})

    cfg = make_config(tmp_path, max_retries=3)
    with client_with_handler(cfg, handler) as c, pytest.raises(OpenAlexError):
        c.count("works", "f:1")


def test_non_retryable_status_raises_immediately(tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, text="bad request")

    cfg = make_config(tmp_path)
    with client_with_handler(cfg, handler) as c, pytest.raises(OpenAlexError):
        c.count("works", "f:bad")
    assert calls["n"] == 1  # no retries for a 400


def test_group_by_parsing(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "meta": {"count": 100},
                "group_by": [
                    {"key": "2018", "key_display_name": "2018", "count": 60},
                    {"key": "2019", "key_display_name": "2019", "count": 40},
                ],
            },
        )

    cfg = make_config(tmp_path)
    with client_with_handler(cfg, handler) as c:
        buckets = c.group_by("works", "publication_year", "f:1")
    assert {b["key"]: b["count"] for b in buckets} == {"2018": 60, "2019": 40}


def test_pagination_follows_cursor_and_checkpoints(tmp_path):
    import json

    pages = {
        "*": {"results": [{"id": "A"}, {"id": "B"}], "meta": {"next_cursor": "c2"}},
        "c2": {"results": [{"id": "C"}], "meta": {"next_cursor": None}},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        return httpx.Response(200, json=pages[cursor])

    cfg = make_config(tmp_path)
    checkpoint = tmp_path / "cursor.json"
    with client_with_handler(cfg, handler) as c:
        ids = [row["id"] for row in c.paginate("works", filters="f:1", checkpoint_path=checkpoint)]
    assert ids == ["A", "B", "C"]
    state = json.loads(checkpoint.read_text())
    assert state["done"] is True  # finished -> marked done, not restartable


def test_finished_checkpoint_does_not_restart(tmp_path):
    import json

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"results": [{"id": "A"}], "meta": {"next_cursor": None}})

    cfg = make_config(tmp_path, cache_enabled=False)
    checkpoint = tmp_path / "cp.json"
    # Pre-write a DONE checkpoint with the matching query id.
    import hashlib
    qid = hashlib.sha256(f"works|f:1|None|{sorted([])}".encode()).hexdigest()[:16]
    checkpoint.write_text(json.dumps({"query_id": qid, "cursor": None, "done": True}))
    with client_with_handler(cfg, handler) as c:
        ids = [r["id"] for r in c.paginate("works", filters="f:1", checkpoint_path=checkpoint)]
    assert ids == []  # finished collection yields nothing
    assert calls["n"] == 0


def test_checkpoint_query_mismatch_ignored(tmp_path):
    import json

    pages = {"*": {"results": [{"id": "A"}], "meta": {"next_cursor": None}}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=pages[request.url.params.get("cursor")])

    cfg = make_config(tmp_path, cache_enabled=False)
    checkpoint = tmp_path / "cp.json"
    # Checkpoint from a DIFFERENT query -> must be ignored, collection starts at *.
    checkpoint.write_text(json.dumps({"query_id": "other", "cursor": "zzz", "done": False}))
    with client_with_handler(cfg, handler) as c:
        ids = [r["id"] for r in c.paginate("works", filters="f:1", checkpoint_path=checkpoint)]
    assert ids == ["A"]


def test_cache_envelope_has_provenance(tmp_path):
    import json

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"meta": {"count": 3}, "results": []},
                              headers={"Date": "Wed, 21 Nov 2026 00:00:00 GMT"})

    cfg = make_config(tmp_path)
    with client_with_handler(cfg, handler) as c:
        c.count("works", "f:1")
    cache_file = next(cfg.cache_dir.glob("*.json"))
    env = json.loads(cache_file.read_text())
    assert env["__slpe_cache__"] == 1
    assert env["response_date"] == "Wed, 21 Nov 2026 00:00:00 GMT"
    assert "fetched_utc" in env and "collector_version" in env
    assert "api_key" not in env["url"] and "mailto" not in env["url"]


def test_groupby_truncation_warns(tmp_path, caplog):
    import logging

    def handler(request: httpx.Request) -> httpx.Response:
        buckets = [{"key": str(i), "count": 1} for i in range(5)]
        return httpx.Response(200, json={"meta": {"count": 5}, "group_by": buckets})

    cfg = make_config(tmp_path)
    with client_with_handler(cfg, handler) as c:
        with caplog.at_level(logging.WARNING, logger="slpe.openalex"):
            c.group_by("works", "primary_topic.subfield.id", "f:1", per_page=5)
    assert any("truncated" in r.message for r in caplog.records)


def _three_page_handler():
    pages = {
        "*": {"results": [{"id": "A"}, {"id": "B"}], "meta": {"next_cursor": "c2"}},
        "c2": {"results": [{"id": "C"}, {"id": "D"}], "meta": {"next_cursor": "c3"}},
        "c3": {"results": [{"id": "E"}], "meta": {"next_cursor": None}},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=pages[request.url.params.get("cursor")])

    return handler


def test_fetch_pages_persists_all_and_counts(tmp_path):
    persisted = []

    def on_page(rows, page_index):
        persisted.extend(r["id"] for r in rows)

    cfg = make_config(tmp_path, cache_enabled=False)
    with client_with_handler(cfg, _three_page_handler()) as c:
        total = c.fetch_pages("works", on_page, filters="f:1",
                              checkpoint_path=tmp_path / "cp.json")
    assert total == 5
    assert persisted == ["A", "B", "C", "D", "E"]


def test_fetch_pages_resumes_after_persistence_failure(tmp_path):
    # Fail while persisting the 2nd page -> checkpoint must still point at page 2,
    # so a resume re-fetches and re-persists it (no silent data loss).
    cfg = make_config(tmp_path, cache_enabled=False)
    checkpoint = tmp_path / "cp.json"

    seen_first_run = []

    def on_page_fail(rows, page_index):
        if page_index == 1:
            raise RuntimeError("disk full during persist")
        seen_first_run.extend(r["id"] for r in rows)

    with client_with_handler(cfg, _three_page_handler()) as c, pytest.raises(RuntimeError):
        c.fetch_pages("works", on_page_fail, filters="f:1", checkpoint_path=checkpoint)
    assert seen_first_run == ["A", "B"]  # only page 0 persisted

    # Resume: page 1 (C, D) must be re-delivered, then page 2 (E).
    resumed = []

    def on_page_ok(rows, page_index):
        resumed.extend(r["id"] for r in rows)

    with client_with_handler(cfg, _three_page_handler()) as c:
        total = c.fetch_pages("works", on_page_ok, filters="f:1", checkpoint_path=checkpoint)
    assert resumed == ["C", "D", "E"]  # resumed exactly where it failed
    assert total == 5


def test_fetch_pages_max_records_is_page_aligned_no_loss(tmp_path):
    # The cap is page-aligned: whole pages are persisted (never sliced), so no
    # record is dropped. With pages of 2 and max_records=3, it stops AFTER the
    # page that crosses the cap -> A,B,C,D (overshoots to a page boundary).
    collected = []

    def on_page(rows, page_index):
        collected.extend(r["id"] for r in rows)

    cfg = make_config(tmp_path, cache_enabled=False)
    with client_with_handler(cfg, _three_page_handler()) as c:
        total = c.fetch_pages("works", on_page, filters="f:1", max_records=3,
                              checkpoint_path=tmp_path / "cp.json")
    assert total == 4
    assert collected == ["A", "B", "C", "D"]  # full pages, nothing sliced/lost


def test_fetch_pages_partial_can_be_expanded(tmp_path):
    # A capped run saves status 'partial' (not complete), so a later run CONTINUES
    # instead of being blocked as finished (the 4.1 bug).
    import json
    cfg = make_config(tmp_path, cache_enabled=False)
    checkpoint = tmp_path / "cp.json"

    first = []
    with client_with_handler(cfg, _three_page_handler()) as c:
        c.fetch_pages("works", lambda rows, i: first.extend(r["id"] for r in rows),
                      filters="f:1", max_records=2, checkpoint_path=checkpoint)
    assert first == ["A", "B"]
    assert json.loads(checkpoint.read_text())["status"] == "partial"

    # Resume with a larger cap -> continues from the saved cursor.
    more = []
    with client_with_handler(cfg, _three_page_handler()) as c:
        c.fetch_pages("works", lambda rows, i: more.extend(r["id"] for r in rows),
                      filters="f:1", max_records=10, checkpoint_path=checkpoint)
    assert more == ["C", "D", "E"]
    assert json.loads(checkpoint.read_text())["status"] == "complete"


def test_fetch_pages_complete_does_not_restart(tmp_path):
    cfg = make_config(tmp_path, cache_enabled=False)
    checkpoint = tmp_path / "cp.json"
    with client_with_handler(cfg, _three_page_handler()) as c:
        c.fetch_pages("works", lambda rows, i: None, filters="f:1", checkpoint_path=checkpoint)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json={"results": [{"id": "Z"}], "meta": {"next_cursor": None}})

    with client_with_handler(make_config(tmp_path, cache_enabled=False), handler) as c:
        got = []
        c.fetch_pages("works", lambda rows, i: got.extend(rows), filters="f:1",
                      checkpoint_path=checkpoint)
    assert got == [] and calls["n"] == 0
