"""OpenAlex HTTP client with caching, retries, throttling and accounting.

Responsibilities (project requirement I.3):
    * Authentication: polite-pool ``mailto`` + optional ``api_key`` (env only).
    * Pagination: cursor paging for arbitrarily large result sets.
    * Robustness: progressive backoff retries that honour ``Retry-After``.
    * Rate limiting: a minimum interval between outgoing requests.
    * Persistent on-disk cache keyed by the normalized request URL -> resumable.
    * Accounting: number of requests, cache hits, bytes downloaded.
    * Never fabricates data: on exhausted retries it raises, returning nothing.

Only JSON GET endpoints are used. The client is deliberately thin: higher-level
stages (characterization, corpus building) compose ``count``/``group_by``/
``paginate`` rather than embedding URL logic.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from slpe.config import OpenAlexConfig

logger = logging.getLogger("slpe.openalex")

# HTTP statuses worth retrying (transient): rate limit + server/proxy errors.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# Bumped when the collection logic changes in a way that invalidates cached bodies.
COLLECTOR_VERSION = "1.0"
_CACHE_MARKER = "__slpe_cache__"


class OpenAlexError(RuntimeError):
    """Raised when a request ultimately fails (after retries) or returns bad data."""


@dataclass
class RequestStats:
    """Mutable counters for a collection run; serialized into run manifests."""

    n_requests: int = 0          # actual network requests (cache misses)
    n_cache_hits: int = 0
    n_retries: int = 0
    n_network_errors: int = 0    # transport failures before any HTTP response
    bytes_downloaded: int = 0
    seconds_waiting: float = 0.0  # time spent sleeping (throttle + backoff)

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_requests": self.n_requests,
            "n_cache_hits": self.n_cache_hits,
            "n_retries": self.n_retries,
            "n_network_errors": self.n_network_errors,
            "bytes_downloaded": self.bytes_downloaded,
            "seconds_waiting": round(self.seconds_waiting, 3),
            # NOTE: n_cache_hits reflects reuse in THIS run; a warm-cache rerun with
            # n_requests==0 does not mean the original collection was free.
        }


@dataclass
class OpenAlexClient:
    """Thin, cached, rate-limited OpenAlex JSON client.

    Construct with :meth:`from_config`. All public methods are synchronous.
    """

    config: OpenAlexConfig
    stats: RequestStats = field(default_factory=RequestStats)
    _client: httpx.Client | None = field(default=None, repr=False)
    _last_request_ts: float = field(default=0.0, repr=False)

    # --- construction ------------------------------------------------------
    @classmethod
    def from_config(cls, config: OpenAlexConfig) -> OpenAlexClient:
        if config.cache_enabled:
            config.cache_dir.mkdir(parents=True, exist_ok=True)
        headers = {"User-Agent": _user_agent(config), "Accept": "application/json"}
        client = httpx.Client(timeout=config.timeout_seconds, headers=headers)
        return cls(config=config, _client=client)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> OpenAlexClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- low-level GET -----------------------------------------------------
    def _auth_params(self, params: dict[str, Any]) -> dict[str, Any]:
        out = dict(params)
        if self.config.mailto:
            out.setdefault("mailto", self.config.mailto)
        if self.config.api_key:
            out.setdefault("api_key", self.config.api_key)
        return out

    def _canonical_url(self, url: str, params: dict[str, Any]) -> str:
        # Exclude secrets (api_key AND mailto) so the stored URL is shareable.
        cache_params = {k: v for k, v in sorted(params.items()) if k not in ("api_key", "mailto")}
        return f"{url}?{urlencode(cache_params)}"

    def _cache_path(self, url: str, params: dict[str, Any]) -> Path:
        digest = hashlib.sha256(self._canonical_url(url, params).encode("utf-8")).hexdigest()
        return self.config.cache_dir / f"{digest}.json"

    def _read_cache(self, cache_path: Path) -> dict[str, Any] | None:
        """Return the cached body, honouring provenance envelope + max age.

        Backward-compatible: legacy entries are raw response bodies (no envelope);
        they are returned as-is. New entries are envelopes carrying provenance.
        """
        try:
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cache_path.unlink(missing_ok=True)
            return None
        if isinstance(raw, dict) and raw.get(_CACHE_MARKER):
            max_age = self.config.cache_max_age_days
            if max_age is not None:
                fetched = raw.get("fetched_utc")
                if fetched:
                    age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(fetched)).days
                    if age_days > max_age:
                        logger.info("cache entry older than %s days; refetching", max_age)
                        return None
            return raw.get("body")
        return raw  # legacy raw-body entry

    def _write_cache(
        self, cache_path: Path, body: dict[str, Any], url_no_secret: str, response_date: str | None
    ) -> None:
        envelope = {
            _CACHE_MARKER: 1,
            "collector_version": COLLECTOR_VERSION,
            "fetched_utc": datetime.now(timezone.utc).isoformat(),
            "response_date": response_date,  # OpenAlex 'Date' header (when the server served it)
            "url": url_no_secret,
            "body": body,
        }
        tmp = cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(envelope), encoding="utf-8")
        tmp.replace(cache_path)  # atomic write -> safe to interrupt mid-run

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_ts
        wait = self.config.min_interval_seconds - elapsed
        if wait > 0:
            time.sleep(wait)
            self.stats.seconds_waiting += wait

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET a JSON resource with caching, throttling and retries.

        Args:
            path: endpoint path, e.g. ``"works"`` or ``"fields/17"``.
            params: query parameters (``mailto``/``api_key`` are added automatically).

        Returns:
            Parsed JSON object.

        Raises:
            OpenAlexError: on exhausted retries or a non-retryable HTTP error.
        """
        if self._client is None:
            raise OpenAlexError("client is closed")
        params = dict(params or {})
        url = f"{self.config.base_url}/{path.lstrip('/')}"

        cache_path = self._cache_path(url, params) if self.config.cache_enabled else None
        if cache_path is not None and cache_path.exists() and not self.config.refresh_cache:
            body = self._read_cache(cache_path)
            if body is not None:
                self.stats.n_cache_hits += 1
                return body

        full_params = self._auth_params(params)
        payload, response_date = self._get_with_retries(url, full_params)

        if cache_path is not None:
            self._write_cache(cache_path, payload, self._canonical_url(url, params), response_date)
        return payload

    def _get_with_retries(self, url: str, params: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        assert self._client is not None
        backoff = self.config.backoff_initial_seconds
        last_exc: Exception | None = None

        for attempt in range(1, self.config.max_retries + 1):
            self._throttle()
            try:
                self._last_request_ts = time.monotonic()
                resp = self._client.get(url, params=params)
            except httpx.RequestError as exc:  # network/DNS/timeout
                last_exc = exc
                self.stats.n_network_errors += 1
                logger.warning("request error (attempt %d/%d): %s", attempt, self.config.max_retries, exc)
            else:
                self.stats.n_requests += 1
                self.stats.bytes_downloaded += len(resp.content)
                if resp.status_code == 200:
                    try:
                        return resp.json(), resp.headers.get("Date")
                    except json.JSONDecodeError as exc:
                        raise OpenAlexError(f"non-JSON 200 response from {url}") from exc
                if resp.status_code not in _RETRYABLE_STATUS:
                    raise OpenAlexError(
                        f"HTTP {resp.status_code} for {url}: {resp.text[:300]}"
                    )
                last_exc = OpenAlexError(f"HTTP {resp.status_code}")
                retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                if retry_after is not None:
                    backoff = max(backoff, retry_after)
                logger.warning(
                    "retryable HTTP %s (attempt %d/%d), sleeping %.1fs",
                    resp.status_code, attempt, self.config.max_retries, backoff,
                )

            if attempt < self.config.max_retries:
                self.stats.n_retries += 1
                time.sleep(backoff)
                self.stats.seconds_waiting += backoff
                backoff = min(backoff * 2, self.config.backoff_max_seconds)

        raise OpenAlexError(f"exhausted {self.config.max_retries} retries for {url}") from last_exc

    # --- high-level helpers ------------------------------------------------
    def count(self, path: str, filters: str | None = None, **extra: Any) -> int:
        """Return ``meta.count`` for a query without downloading result rows."""
        params: dict[str, Any] = {"per-page": 1, "select": "id"}
        if filters:
            params["filter"] = filters
        params.update(extra)
        payload = self.get(path, params)
        return int(payload["meta"]["count"])

    def group_by(
        self, path: str, group_by: str, filters: str | None = None, **extra: Any
    ) -> list[dict[str, Any]]:
        """Return the ``group_by`` aggregation buckets (``[{key, key_display_name, count}]``).

        Warns if the number of buckets equals the page cap, which may indicate the
        aggregation was truncated and some groups are missing.
        """
        per_page = int(extra.pop("per_page", 200))
        params: dict[str, Any] = {"group_by": group_by, "per-page": per_page}
        if filters:
            params["filter"] = filters
        params.update(extra)
        payload = self.get(path, params)
        buckets = list(payload.get("group_by", []))
        if len(buckets) >= per_page:
            logger.warning(
                "group_by '%s' returned %d buckets (page cap %d) — results may be "
                "truncated; filters=%s", group_by, len(buckets), per_page, filters,
            )
        return buckets

    def get_single(self, path: str, **extra: Any) -> dict[str, Any]:
        """Fetch a single entity (e.g. ``fields/17``)."""
        return self.get(path, dict(extra))

    def list_all(self, path: str, filters: str | None = None, **extra: Any) -> list[dict[str, Any]]:
        """Fetch every row of a *small* list endpoint in one page (e.g. the 26 fields)."""
        params: dict[str, Any] = {"per-page": extra.pop("per_page", 200)}
        if filters:
            params["filter"] = filters
        params.update(extra)
        payload = self.get(path, params)
        return list(payload.get("results", []))

    def paginate(
        self,
        path: str,
        *,
        filters: str | None = None,
        select: str | None = None,
        per_page: int | None = None,
        checkpoint_path: str | Path | None = None,
        **extra: Any,
    ) -> Iterator[dict[str, Any]]:
        """Yield every result row via cursor pagination (resumable).

        Cursor paging (``cursor=*``) scales to millions of rows. Each page is
        cached, so re-running replays from disk cheaply.

        Checkpointing contract (``checkpoint_path``): the checkpoint stores the
        query identity (a hash of path+filters+select) alongside the next cursor.
        The cursor advances only AFTER the consumer signals the page is durably
        persisted — call the yielded generator's ``.send(True)`` is not used;
        instead the cursor is written only once the page's rows have all been
        yielded AND the next page is requested, so a crash mid-page re-requests
        that page on resume (at-least-once delivery; the consumer must dedupe by
        work id). A saved cursor is IGNORED if its query identity differs, so a
        checkpoint can never be applied to a different query. A completed run
        writes an explicit ``DONE`` marker; re-running a finished collection then
        yields nothing instead of restarting from scratch.

        Yields:
            One work/entity dict at a time (never holds the full set in memory).
        """
        per_page = per_page or self.config.per_page
        query_id = hashlib.sha256(
            f"{path}|{filters}|{select}|{sorted(extra.items())}".encode()
        ).hexdigest()[:16]

        cursor = "*"
        cp = Path(checkpoint_path) if checkpoint_path is not None else None
        if cp is not None and cp.exists():
            try:
                state = json.loads(cp.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                state = {}
            if state.get("query_id") == query_id:
                if state.get("done"):
                    return  # finished collection; do not restart
                cursor = state.get("cursor") or "*"
            else:
                logger.warning("checkpoint query mismatch; ignoring saved cursor")

        def _save(cur: str | None, done: bool) -> None:
            if cp is not None:
                cp.write_text(
                    json.dumps({"query_id": query_id, "cursor": cur, "done": done}),
                    encoding="utf-8",
                )

        while cursor:
            params: dict[str, Any] = {"per-page": per_page, "cursor": cursor}
            if filters:
                params["filter"] = filters
            if select:
                params["select"] = select
            params.update(extra)
            payload = self.get(path, params)

            results = payload.get("results", [])
            for row in results:
                yield row

            next_cursor = payload.get("meta", {}).get("next_cursor")
            if not results or not next_cursor:
                _save(None, done=True)
                break
            cursor = next_cursor
            _save(cursor, done=False)

    def fetch_pages(
        self,
        path: str,
        on_page: Callable[[list[dict[str, Any]], int], None],
        *,
        filters: str | None = None,
        select: str | None = None,
        per_page: int | None = None,
        checkpoint_path: str | Path | None = None,
        max_records: int | None = None,
        **extra: Any,
    ) -> int:
        """Page through results with TRANSACTIONAL checkpointing.

        For each page, ``on_page(rows, page_index)`` is called to persist the rows.
        The checkpoint cursor advances **only after** ``on_page`` returns without
        raising — so a crash during persistence re-fetches the same page on resume
        (at-least-once; dedupe downstream by work id). This fixes the weaker
        guarantee of :meth:`paginate`, where the cursor advanced before the consumer
        confirmed durability.

        The checkpoint is bound to the query identity (path+filters+select+extra); a
        saved cursor from a different query is ignored. The checkpoint records a
        ``status`` (NOT a plain done flag), distinguishing:

            * ``complete``    — the query universe was exhausted (no next cursor);
                                re-running yields nothing.
            * ``partial``     — stopped at ``max_records`` though more data exists;
                                re-running (optionally with a larger cap) CONTINUES
                                from the saved cursor, so a capped pilot can be
                                expanded later. This is the bug this state fixes.
            * ``interrupted`` — a saved cursor from a run that did not finish (process
                                died); resuming continues from it.
            * ``failed``      — ``on_page`` raised; the cursor was not advanced, so a
                                resume re-fetches and re-persists the in-flight page.

        Args:
            on_page: callback that durably persists a page's rows; must raise on
                failure so the cursor is not advanced.
            max_records: optional cap on total records fetched (for test/pilot modes).

        Returns:
            Total number of records delivered to ``on_page`` across all runs.
        """
        per_page = per_page or self.config.per_page
        query_id = hashlib.sha256(
            f"{path}|{filters}|{select}|{sorted(extra.items())}".encode()
        ).hexdigest()[:16]

        cp = Path(checkpoint_path) if checkpoint_path is not None else None
        cursor = "*"
        page_index = 0
        total = 0
        if cp is not None and cp.exists():
            try:
                state = json.loads(cp.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                state = {}
            if state.get("query_id") == query_id:
                status = state.get("status")
                if status == "complete":
                    return int(state.get("total", 0))  # universe exhausted
                # partial / interrupted / failed -> continue from saved cursor.
                cursor = state.get("cursor") or "*"
                page_index = int(state.get("page_index", 0))
                total = int(state.get("total", 0))
            else:
                logger.warning("checkpoint query mismatch; starting fresh")

        def _save(cur: str | None, status: str) -> None:
            if cp is not None:
                tmp = cp.with_suffix(".tmp")
                tmp.write_text(json.dumps({
                    "query_id": query_id, "cursor": cur, "status": status,
                    "page_index": page_index, "total": total,
                }), encoding="utf-8")
                tmp.replace(cp)

        while cursor:
            params: dict[str, Any] = {"per-page": per_page, "cursor": cursor}
            if filters:
                params["filter"] = filters
            if select:
                params["select"] = select
            params.update(extra)
            payload = self.get(path, params)
            results = payload.get("results", [])

            # NOTE: full pages are persisted whole — we never slice a page to hit
            # max_records, because slicing + advancing the cursor would silently
            # drop the page's remainder on resume. The cap is therefore PAGE-ALIGNED
            # (it overshoots by < per_page), which guarantees no record is skipped.

            # Persist FIRST; only then advance the checkpoint cursor. If on_page
            # raises, record 'failed' (cursor unchanged) and re-raise.
            try:
                on_page(results, page_index)
            except Exception:
                _save(cursor, "failed")
                raise
            total += len(results)
            page_index += 1

            next_cursor = payload.get("meta", {}).get("next_cursor")
            exhausted = not results or not next_cursor
            reached_cap = max_records is not None and total >= max_records
            if exhausted:
                _save(None, "complete")
                break
            if reached_cap:
                # More data exists; keep the cursor so a later run can continue.
                _save(next_cursor, "partial")
                break
            cursor = next_cursor
            _save(cursor, "interrupted")  # in-flight; becomes 'complete' when done

        return total


def _user_agent(config: OpenAlexConfig) -> str:
    base = "scientific-link-prediction-experiments/0.1 (research; +https://openalex.org)"
    if config.mailto:
        return f"{base} mailto:{config.mailto}"
    return base


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)  # delta-seconds form
    except ValueError:
        return None  # HTTP-date form is rare here; fall back to exponential backoff
