"""HTTP fetching for the widget crawler: SSRF-safe, manual redirects, size limits and robots.txt."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlsplit
from urllib.request import getproxies
from urllib.robotparser import RobotFileParser

import aiohttp
from open_webui.env import AIOHTTP_CLIENT_SESSION_SSL
from open_webui.retrieval.web.utils import get_ssrf_safe_session, validate_url, _SSRFSafeConnector
from open_webui.utils.widget_crawl_urls import (
    CRAWLER_ROBOTS_TOKEN,
    CRAWLER_USER_AGENT,
    MAX_PAGE_BYTES,
    MAX_REDIRECTS,
    MAX_ROBOTS_BYTES,
    normalize_url,
)

REDIRECT_STATUSES = {301, 302, 303, 307, 308}
log = logging.getLogger(__name__)


def widget_http_session():
    """Only an administrator can opt in to the server's trusted proxy configuration.

    Destination URLs remain validated. A proxy resolves destinations remotely, so
    the administrator must ensure that proxy also blocks internal destinations.
    """
    if os.environ.get('WIDGET_CRAWLER_TRUST_ENV', 'false').lower() != 'true':
        return get_ssrf_safe_session(trust_env=False, store_cookies=False)
    proxies = getproxies()
    proxy_endpoints = set()
    for scheme in ('http', 'https'):
        value = proxies.get(scheme)
        if value:
            parsed = urlsplit(value if '://' in value else 'http://' + value)
            if parsed.hostname:
                proxy_endpoints.add((parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80)))

    class TrustedProxyConnector(_SSRFSafeConnector):
        async def _resolve_host(self, host, port, traces=None):
            if (host, port) in proxy_endpoints:
                return await aiohttp.TCPConnector._resolve_host(self, host, port, traces=traces)
            return await super()._resolve_host(host, port, traces=traces)

    return aiohttp.ClientSession(connector=TrustedProxyConnector(), trust_env=True,
                                 cookie_jar=aiohttp.DummyCookieJar())


@dataclass
class FetchResult:
    url: str
    status: str  # ok | http_error | timeout | blocked | connection_error | too_large | too_many_redirects
    http_status: Optional[int] = None
    content_type: str = ''
    content_length: Optional[int] = None
    body: bytes = b''
    error: Optional[str] = None
    retry_after: Optional[float] = None
    content_disposition: str = ''


def _parse_int(value: Optional[str]) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


class CrawlFetcher:
    def __init__(self, timeout_seconds: int, request_delay_ms: int = 0, max_retries: int = 2):
        self.delay = request_delay_ms / 1000
        self.max_retries = max_retries
        self._pace_lock = asyncio.Lock()
        self._next_request = 0.0
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.session: Optional[aiohttp.ClientSession] = None
        self._robots: dict[str, Optional[RobotFileParser]] = {}
        self._robots_lock = asyncio.Lock()

    async def __aenter__(self) -> 'CrawlFetcher':
        self.session = widget_http_session()
        return self

    async def __aexit__(self, *exc) -> None:
        if self.session:
            await self.session.close()

    async def _pace(self):
        async with self._pace_lock:
            while self._next_request > time.monotonic():
                await asyncio.sleep(self._next_request - time.monotonic())
            self._next_request = time.monotonic() + self.delay

    async def fetch(self, url: str, method: str = 'GET',
                    max_bytes: int = MAX_PAGE_BYTES, read_body: bool = True) -> FetchResult:
        for attempt in range(self.max_retries + 1):
            result = await self._fetch_once(url, method, max_bytes, read_body)
            if result.http_status != 429 and result.status != 'timeout':
                return result
            delay = max(result.retry_after or 0, 5 * (2 ** attempt))
            if result.http_status == 429:
                # Share the cooldown with all workers, including sitemap/file requests.
                self._next_request = max(self._next_request, time.monotonic() + delay)
            if attempt == self.max_retries or delay > 300:
                return result
            await asyncio.sleep(delay)
        return result

    async def _fetch_once(
        self,
        url: str,
        method: str = 'GET',
        max_bytes: int = MAX_PAGE_BYTES,
        read_body: bool = True,
    ) -> FetchResult:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            try:
                await asyncio.to_thread(validate_url, current)
            except ValueError:
                return FetchResult(url=current, status='blocked')

            try:
                await self._pace()
                async with self.session.request(
                    method,
                    current,
                    allow_redirects=False,
                    timeout=self.timeout,
                    headers={'User-Agent': CRAWLER_USER_AGENT, 'Accept': '*/*'},
                    ssl=AIOHTTP_CLIENT_SESSION_SSL,
                ) as response:
                    if response.status in REDIRECT_STATUSES:
                        location = response.headers.get('Location')
                        next_url = normalize_url(urljoin(current, location)) if location else None
                        if not next_url:
                            return FetchResult(url=current, status='http_error', http_status=response.status)
                        current = next_url
                        continue

                    content_type = response.headers.get('Content-Type', '')
                    content_length = _parse_int(response.headers.get('Content-Length'))

                    if response.status >= 400:
                        detail = f'Website returned HTTP {response.status}.'
                        if response.status == 429:
                            detail += ' The website is rate limiting requests; try again later with a longer request delay and lower concurrency.'
                        retry_after = response.headers.get('Retry-After')
                        retry_seconds = None
                        if retry_after:
                            try:
                                retry_seconds = max(0, float(retry_after))
                            except ValueError:
                                try:
                                    retry_seconds = max(0, (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds())
                                except (ValueError, TypeError, OverflowError):
                                    pass
                        if retry_after:
                            detail += f' Retry-After: {retry_after[:100]}.'
                        log.warning('Widget crawl fetch %s %s: %s', method, current, detail)
                        return FetchResult(
                            url=current, status='http_error', http_status=response.status, content_type=content_type,
                            content_disposition=response.headers.get('Content-Disposition', ''),
                            error=detail, retry_after=retry_seconds,
                        )

                    if method == 'HEAD' or not read_body:
                        return FetchResult(
                            url=current,
                            status='ok',
                            http_status=response.status,
                            content_type=content_type,
                            content_disposition=response.headers.get('Content-Disposition', ''),
                            content_length=content_length,
                        )

                    if content_length is not None and content_length > max_bytes:
                        return FetchResult(
                            url=current,
                            status='too_large',
                            http_status=response.status,
                            content_type=content_type,
                            content_disposition=response.headers.get('Content-Disposition', ''),
                            content_length=content_length,
                        )

                    chunks = []
                    total = 0
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        total += len(chunk)
                        if total > max_bytes:
                            return FetchResult(
                                url=current,
                                status='too_large',
                                http_status=response.status,
                                content_type=content_type,
                                content_disposition=response.headers.get('Content-Disposition', ''),
                                content_length=content_length,
                            )
                        chunks.append(chunk)

                    return FetchResult(
                        url=current,
                        status='ok',
                        http_status=response.status,
                        content_type=content_type,
                        content_disposition=response.headers.get('Content-Disposition', ''),
                        content_length=content_length if content_length is not None else total,
                        body=b''.join(chunks),
                    )
            except (asyncio.TimeoutError, ValueError, aiohttp.ClientError) as exc:
                status = ('timeout' if isinstance(exc, asyncio.TimeoutError) else
                          'blocked' if isinstance(exc, ValueError) else 'connection_error')
                detail = f'{type(exc).__name__}: {str(exc) or "Request timed out"}'[:1000]
                log.warning('Widget crawl fetch %s %s failed: %s', method, current, detail)
                return FetchResult(url=current, status=status, error=detail)

        return FetchResult(url=current, status='too_many_redirects')

    async def get_robots(self, origin: str) -> Optional[RobotFileParser]:
        """Return the parsed robots.txt for an origin, or None when it is missing/unreadable (allow all)."""
        async with self._robots_lock:
            if origin not in self._robots:
                result = await self.fetch(f'{origin}/robots.txt', max_bytes=MAX_ROBOTS_BYTES)
                if result.status != 'ok':
                    self._robots[origin] = None
                else:
                    parser = RobotFileParser()
                    parser.parse(result.body.decode('utf-8', errors='replace').splitlines())
                    self._robots[origin] = parser
            return self._robots[origin]

    async def robots_allows(self, url: str) -> bool:
        parts = urlsplit(url)
        parser = await self.get_robots(f'{parts.scheme}://{parts.netloc}')
        return True if parser is None else parser.can_fetch(CRAWLER_ROBOTS_TOKEN, url)
