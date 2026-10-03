"""HTTP fetching for the widget crawler: SSRF-safe, manual redirects, size limits and robots.txt."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import aiohttp
from open_webui.env import AIOHTTP_CLIENT_SESSION_SSL
from open_webui.retrieval.web.utils import get_ssrf_safe_session, validate_url
from open_webui.utils.widget_crawl_urls import (
    CRAWLER_ROBOTS_TOKEN,
    CRAWLER_USER_AGENT,
    MAX_PAGE_BYTES,
    MAX_REDIRECTS,
    MAX_ROBOTS_BYTES,
    normalize_url,
)

REDIRECT_STATUSES = {301, 302, 303, 307, 308}


@dataclass
class FetchResult:
    url: str
    status: str  # ok | http_error | timeout | blocked | connection_error | too_large | too_many_redirects
    http_status: Optional[int] = None
    content_type: str = ''
    content_length: Optional[int] = None
    body: bytes = b''


def _parse_int(value: Optional[str]) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


class CrawlFetcher:
    def __init__(self, timeout_seconds: int):
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.session: Optional[aiohttp.ClientSession] = None
        self._robots: dict[str, Optional[RobotFileParser]] = {}
        self._robots_lock = asyncio.Lock()

    async def __aenter__(self) -> 'CrawlFetcher':
        self.session = get_ssrf_safe_session(trust_env=False, store_cookies=False)
        return self

    async def __aexit__(self, *exc) -> None:
        if self.session:
            await self.session.close()

    async def fetch(
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
                        return FetchResult(
                            url=current, status='http_error', http_status=response.status, content_type=content_type
                        )

                    if method == 'HEAD' or not read_body:
                        return FetchResult(
                            url=current,
                            status='ok',
                            http_status=response.status,
                            content_type=content_type,
                            content_length=content_length,
                        )

                    if content_length is not None and content_length > max_bytes:
                        return FetchResult(
                            url=current,
                            status='too_large',
                            http_status=response.status,
                            content_type=content_type,
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
                                content_length=content_length,
                            )
                        chunks.append(chunk)

                    return FetchResult(
                        url=current,
                        status='ok',
                        http_status=response.status,
                        content_type=content_type,
                        content_length=content_length if content_length is not None else total,
                        body=b''.join(chunks),
                    )
            except asyncio.TimeoutError:
                return FetchResult(url=current, status='timeout')
            except ValueError:
                return FetchResult(url=current, status='blocked')
            except aiohttp.ClientError:
                return FetchResult(url=current, status='connection_error')

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
