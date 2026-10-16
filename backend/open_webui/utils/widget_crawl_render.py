"""JavaScript rendering for the widget crawler (React, Vite, Vue and other client-rendered sites).

Pages are fetched with plain HTTP first. Only pages whose HTML has no readable text, which is what
a single-page app shell looks like, are loaded again in headless Chromium. The browser starts on the
first page that needs it, so sites that serve normal HTML never start one.

Every request the browser makes goes through route interception and is fetched by an SSRF-safe
aiohttp session, so the browser can never reach an address the crawler itself may not.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin

import aiohttp
from open_webui.config import PLAYWRIGHT_WS_URL
from open_webui.env import AIOHTTP_CLIENT_SESSION_SSL
from open_webui.retrieval.web.utils import (
    _forwardable_request_headers,
    _fulfillable_response_headers,
    get_ssrf_safe_session,
    validate_url,
)
from open_webui.utils.widget_crawl_urls import MAX_REDIRECTS, MIN_PAGE_TEXT_CHARS

log = logging.getLogger(__name__)

RENDER_MODES = ('auto', 'always', 'never')
# Not needed for text, and usually most of a page's bytes.
BLOCKED_RESOURCE_TYPES = {'image', 'media', 'font'}
# JavaScript bundles can be far larger than the HTML page itself.
MAX_RESOURCE_BYTES = 20 * 1024 * 1024
# After the DOM is ready, how long to wait for the app to fetch its data and render.
MAX_SETTLE_MS = 8000
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
BROWSER_CHANNELS = (None, 'chrome', 'msedge')

UNAVAILABLE_MESSAGE = (
    'JavaScript rendering is not available. Install the browser with "playwright install chromium", '
    'or set PLAYWRIGHT_WS_URL to a Playwright server.'
)

# A mount point such as <div id="root"></div> plus a module script is the shape of a SPA shell.
_APP_ROOT_RE = re.compile(
    r'<div[^>]+id=["\'](?:root|app|__next|__nuxt|svelte|main)["\'][^>]*>\s*</div>',
    re.IGNORECASE,
)
_MODULE_SCRIPT_RE = re.compile(r'<script[^>]+type=["\']module["\']', re.IGNORECASE)


def needs_rendering(mode: str, html: str, text: str) -> bool:
    """Decide whether a page fetched over plain HTTP should be loaded again in the browser."""
    if mode == 'never':
        return False
    if mode == 'always':
        return True
    if len(text.strip()) < MIN_PAGE_TEXT_CHARS:
        return True
    # Some shells ship a little static text (a "loading" line, a noscript notice) next to the app.
    return bool(_APP_ROOT_RE.search(html) and _MODULE_SCRIPT_RE.search(html) and len(text.strip()) < 500)


@dataclass
class RenderResult:
    url: str
    status: str  # ok | http_error | timeout | failed | unavailable
    http_status: Optional[int] = None
    html: str = ''
    error: Optional[str] = None


class CrawlRenderer:
    """Lazily started headless browser shared by all pages of one crawl run."""

    def __init__(self, timeout_seconds: int):
        self.timeout_ms = timeout_seconds * 1000
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.available: Optional[bool] = None
        self.error: Optional[str] = None
        self.engine: Optional[str] = None
        self.pages_rendered = 0
        self.bytes_downloaded = 0
        self._lock = asyncio.Lock()
        self._playwright = None
        self._browser = None
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> 'CrawlRenderer':
        return self

    async def __aexit__(self, *exc) -> None:
        for close in (
            lambda: self._browser.close() if self._browser else None,
            lambda: self._playwright.stop() if self._playwright else None,
            lambda: self._session.close() if self._session else None,
        ):
            try:
                awaitable = close()
                if awaitable is not None:
                    await awaitable
            except Exception as e:
                log.debug('Widget crawl renderer cleanup failed: %s', e)

    async def _start(self) -> bool:
        async with self._lock:
            if self.available is not None:
                return self.available
            try:
                from playwright.async_api import async_playwright
            except ImportError:
                return self._unavailable('Playwright is not installed')

            try:
                self._playwright = await async_playwright().start()
            except Exception as e:
                return self._unavailable(f'Playwright failed to start: {e}')

            ws_url = await _playwright_ws_url()
            if ws_url:
                try:
                    self._browser = await self._playwright.chromium.connect(ws_url)
                    self.engine = 'remote'
                except Exception as e:
                    return self._unavailable(f'Could not connect to PLAYWRIGHT_WS_URL: {e}')
            else:
                # Bundled Chromium first; an installed Chrome or Edge works as well.
                last_error = None
                for channel in BROWSER_CHANNELS:
                    try:
                        self._browser = await self._playwright.chromium.launch(headless=True, channel=channel)
                        self.engine = channel or 'chromium'
                        break
                    except Exception as e:
                        last_error = e
                if not self._browser:
                    log.debug('Widget crawl renderer launch failed: %s', last_error)
                    return self._unavailable(UNAVAILABLE_MESSAGE)

            self._session = get_ssrf_safe_session(trust_env=False, store_cookies=False)
            self.available = True
            log.info('Widget crawl: JavaScript rendering enabled (%s browser)', self.engine)
            return True

    def _unavailable(self, message: str) -> bool:
        self.available = False
        self.error = message
        log.warning('Widget crawl: %s', message)
        return False

    async def render(self, url: str) -> RenderResult:
        if not await self._start():
            return RenderResult(url=url, status='unavailable', error=self.error)

        context = await self._browser.new_context(java_script_enabled=True, service_workers='block')
        try:
            page = await context.new_page()
            await page.route('**/*', self._intercept)
            await page.route_web_socket('**/*', lambda ws_route: ws_route.close())

            try:
                response = await page.goto(url, wait_until='domcontentloaded', timeout=self.timeout_ms)
            except Exception as e:
                if 'Timeout' in type(e).__name__:
                    return RenderResult(url=url, status='timeout')
                return RenderResult(url=url, status='failed', error=str(e)[:500])

            if response is None:
                return RenderResult(url=url, status='failed', error='No response')
            if response.status >= 400:
                return RenderResult(url=page.url, status='http_error', http_status=response.status)

            await self._settle(page)
            html = await page.content()
            self.pages_rendered += 1
            return RenderResult(url=page.url, status='ok', http_status=response.status, html=html)
        except Exception as e:
            return RenderResult(url=url, status='failed', error=str(e)[:500])
        finally:
            try:
                await context.close()
            except Exception:
                pass

    async def _settle(self, page) -> None:
        """Give the app time to fetch its data and render, without waiting forever on polling apps."""
        budget = min(self.timeout_ms, MAX_SETTLE_MS)
        try:
            await page.wait_for_load_state('networkidle', timeout=budget)
        except Exception:
            pass
        try:
            await page.wait_for_function(
                'min => !!document.body && document.body.innerText.trim().length >= min',
                arg=MIN_PAGE_TEXT_CHARS,
                timeout=min(budget, 3000),
            )
        except Exception:
            pass

    async def _intercept(self, route) -> None:
        request = route.request
        if request.resource_type in BLOCKED_RESOURCE_TYPES or not request.url.startswith(('http://', 'https://')):
            await route.abort()
            return

        try:
            headers = _forwardable_request_headers(await request.all_headers())
            post_data = request.post_data_buffer
            current = request.url
            hop_cookies: list[tuple[str, str]] = []
            for _ in range(MAX_REDIRECTS + 1):
                # The browser would resolve the hostname again after our check, so we fetch it ourselves.
                await asyncio.to_thread(validate_url, current)
                async with self._session.request(
                    request.method,
                    current,
                    headers=headers,
                    data=post_data,
                    allow_redirects=False,
                    timeout=self.timeout,
                    ssl=AIOHTTP_CLIENT_SESSION_SSL,
                ) as response:
                    location = response.headers.get('Location')
                    if response.status in REDIRECT_STATUSES and location:
                        hop_cookies += [('set-cookie', value) for value in response.headers.getall('Set-Cookie', [])]
                        current = urljoin(str(response.url), location)
                        continue

                    body = bytearray()
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        body.extend(chunk)
                        if len(body) > MAX_RESOURCE_BYTES:
                            raise ValueError('Resource too large')
                    self.bytes_downloaded += len(body)
                    await route.fulfill(
                        status=response.status,
                        headers=_fulfillable_response_headers(hop_cookies + list(response.headers.items())),
                        body=bytes(body),
                    )
                    return
            raise ValueError('Too many redirects')
        except Exception as e:
            log.debug('Widget crawl renderer blocked or failed %s: %s', request.url, e)
            try:
                await route.abort()
            except Exception:
                pass


async def _playwright_ws_url() -> str:
    """The admin-saved Web Loader value wins over the environment, as for web search."""
    try:
        from open_webui.retrieval.utils import get_loader_config

        value = (await get_loader_config()).get('playwright_ws_url')
        if value:
            return value
    except Exception as e:
        log.debug('Widget crawl renderer could not read loader config: %s', e)
    return PLAYWRIGHT_WS_URL or ''
