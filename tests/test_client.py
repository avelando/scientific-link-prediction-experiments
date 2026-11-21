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
    with client_with_handler(cfg, handler) as c:
        with pytest.raises(OpenAlexError):
            c.count("works", "f:1")


def test_non_retryable_status_raises_immediately(tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, text="bad request")

    cfg = make_config(tmp_path)
    with client_with_handler(cfg, handler) as c:
        with pytest.raises(OpenAlexError):
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
    pages = {
        "*": {"results": [{"id": "A"}, {"id": "B"}], "meta": {"next_cursor": "c2"}},
        "c2": {"results": [{"id": "C"}], "meta": {"next_cursor": None}},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        return httpx.Response(200, json=pages[cursor])

    cfg = make_config(tmp_path)
    checkpoint = tmp_path / "cursor.txt"
    with client_with_handler(cfg, handler) as c:
        ids = [row["id"] for row in c.paginate("works", filters="f:1", checkpoint_path=checkpoint)]
    assert ids == ["A", "B", "C"]
    assert checkpoint.read_text().strip() == ""  # finished -> empty cursor
