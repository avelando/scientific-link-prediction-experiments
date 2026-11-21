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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlencode

import httpx

from slpe.config import OpenAlexConfig

logger = logging.getLogger("slpe.openalex")

# HTTP statuses worth retrying (transient): rate limit + server/proxy errors.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class OpenAlexError(RuntimeError):
    """Raised when a request ultimately fails (after retries) or returns bad data."""


@dataclass
class RequestStats:
    """Mutable counters for a collection run; serialized into run manifests."""

    n_requests: int = 0          # actual network requests (cache misses)
    n_cache_hits: int = 0
    n_retries: int = 0
    bytes_downloaded: int = 0
    seconds_waiting: float = 0.0  # time spent sleeping (throttle + backoff)

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_requests": self.n_requests,
            "n_cache_hits": self.n_cache_hits,
            "n_retries": self.n_retries,
            "bytes_downloaded": self.bytes_downloaded,
            "seconds_waiting": round(self.seconds_waiting, 3),
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
    def from_config(cls, config: OpenAlexConfig) -> "OpenAlexClient":
        if config.cache_enabled:
            config.cache_dir.mkdir(parents=True, exist_ok=True)
        headers = {"User-Agent": _user_agent(config), "Accept": "application/json"}
        client = httpx.Client(timeout=config.timeout_seconds, headers=headers)
        return cls(config=config, _client=client)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "OpenAlexClient":
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

    def _cache_path(self, url: str, params: dict[str, Any]) -> Path:
        # Exclude the secret api_key from the cache key so cached files are
        # shareable and key rotation doesn't invalidate the cache.
        cache_params = {k: v for k, v in sorted(params.items()) if k != "api_key"}
        canonical = f"{url}?{urlencode(cache_params)}"
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return self.config.cache_dir / f"{digest}.json"

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
        if cache_path is not None and cache_path.exists():
            self.stats.n_cache_hits += 1
            try:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                cache_path.unlink(missing_ok=True)  # corrupt cache entry; refetch

        full_params = self._auth_params(params)
        payload = self._get_with_retries(url, full_params)

        if cache_path is not None:
            tmp = cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(cache_path)  # atomic write -> safe to interrupt mid-run
        return payload

    def _get_with_retries(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
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
                logger.warning("request error (attempt %d/%d): %s", attempt, self.config.max_retries, exc)
            else:
                self.stats.n_requests += 1
                self.stats.bytes_downloaded += len(resp.content)
                if resp.status_code == 200:
                    try:
                        return resp.json()
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
        """Return the ``group_by`` aggregation buckets (``[{key, key_display_name, count}]``)."""
        params: dict[str, Any] = {"group_by": group_by, "per-page": 200}
        if filters:
            params["filter"] = filters
        params.update(extra)
        payload = self.get(path, params)
        return list(payload.get("group_by", []))

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
        cached, so re-running replays from disk cheaply. If ``checkpoint_path`` is
        given, the next cursor is persisted after every page so a *fresh process*
        resumes mid-collection without replaying earlier pages.

        Yields:
            One work/entity dict at a time (never holds the full set in memory).
        """
        per_page = per_page or self.config.per_page
        cursor = "*"
        if checkpoint_path is not None:
            cp = Path(checkpoint_path)
            if cp.exists():
                saved = cp.read_text(encoding="utf-8").strip()
                if saved:
                    cursor = saved

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

            cursor = payload.get("meta", {}).get("next_cursor")
            if checkpoint_path is not None:
                Path(checkpoint_path).write_text(cursor or "", encoding="utf-8")
            if not results:  # defensive: empty page ends iteration
                break


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
