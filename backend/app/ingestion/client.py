"""
Project Argus — Async NAZK API client.

Provides paginated search and single-declaration fetch with retry,
backoff, and configurable concurrency.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

import httpx

logger = logging.getLogger(__name__)

# Default retry / rate-limit settings (overridden from config)
_DEFAULT_CONCURRENCY = 3
_DEFAULT_RETRIES = 3
_DEFAULT_BACKOFF = 1.5  # seconds, doubles each attempt


class NazkClient:
    """Async client for the NAZK public declarations API (v2)."""

    def __init__(
        self,
        base_url: str = "https://public-api.nazk.gov.ua/v2",
        concurrency: int = _DEFAULT_CONCURRENCY,
        max_retries: int = _DEFAULT_RETRIES,
        backoff_base: float = _DEFAULT_BACKOFF,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._semaphore = asyncio.Semaphore(concurrency)
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "NazkClient":
        self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Low-level request with retry
    # ------------------------------------------------------------------

    async def _get(self, url: str, params: dict | None = None) -> dict:
        """Perform a GET request with semaphore, retry, and backoff."""
        assert self._client is not None, "Use `async with NazkClient()` context"

        async with self._semaphore:
            last_exc: Exception | None = None
            for attempt in range(1, self._max_retries + 1):
                try:
                    resp = await self._client.get(url, params=params)
                    resp.raise_for_status()
                    return resp.json()
                except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                    last_exc = exc
                    wait = self._backoff_base * (2 ** (attempt - 1))
                    logger.warning(
                        "NAZK API request failed (attempt %d/%d): %s — retrying in %.1fs",
                        attempt,
                        self._max_retries,
                        exc,
                        wait,
                    )
                    await asyncio.sleep(wait)

            raise RuntimeError(
                f"NAZK API request failed after {self._max_retries} attempts"
            ) from last_exc

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    async def fetch_declaration(self, doc_id: str) -> dict:
        """Fetch a single declaration by its document ID."""
        url = f"{self.base_url}/documents/{doc_id}"
        return await self._get(url)

    async def search_declarations(
        self,
        *,
        query: str | None = None,
        declaration_year: int | None = None,
        declaration_type: int | None = None,
        page: int = 1,
    ) -> dict:
        """Fetch a single page of search results.

        Returns the raw API response dict which contains ``items``
        and pagination metadata.
        """
        url = f"{self.base_url}/documents/list"
        params: dict[str, Any] = {"page": page}
        if query is not None:
            params["query"] = query
        if declaration_year is not None:
            params["declaration_year"] = declaration_year
        if declaration_type is not None:
            params["declaration_type"] = declaration_type
        return await self._get(url, params=params)

    async def iter_declarations(
        self,
        *,
        declaration_year: int | None = None,
        declaration_type: int | None = None,
        max_pages: int = 100,
    ) -> AsyncIterator[dict]:
        """Iterate through all pages of search results, yielding
        individual declaration summary dicts.

        Each yielded dict is a *summary* — use ``fetch_declaration``
        to get the full document.

        Parameters
        ----------
        max_pages:
            Safety cap (API max is 100 anyway).
        """
        for page in range(1, min(max_pages, 100) + 1):
            logger.info("Fetching page %d (year=%s)", page, declaration_year)
            response = await self.search_declarations(
                declaration_year=declaration_year,
                declaration_type=declaration_type,
                page=page,
            )

            items = response.get("items", response.get("data", []))
            if not items:
                logger.info("No more results at page %d, stopping.", page)
                break

            for item in items:
                yield item

            # If fewer items than a full page, we've reached the end
            if len(items) < 100:
                break
