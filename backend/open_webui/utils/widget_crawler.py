"""Crawl job for chat widget website knowledge. Discovers pages, files and resources. Never embeds."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from open_webui.models.chat_widget_crawl import ChatWidgetCrawlItems, ChatWidgetCrawlRuns, ChatWidgetCrawlSettings
from open_webui.utils.widget_crawl_fetch import CrawlFetcher
from open_webui.utils.widget_crawl_urls import (
    HTML_CONTENT_TYPES,
    KEEP_RUNS_PER_WIDGET,
    MAX_CONTEXT_CHARS,
    MAX_ERROR_ITEMS,
    MAX_LINK_TEXT_CHARS,
    MAX_LINKED_ITEMS,
    MAX_PAGE_BYTES,
    MAX_PAGE_TEXT_CHARS,
    MAX_SITEMAP_BYTES,
    MAX_SITEMAP_URLS,
    MAX_SITEMAPS,
    MAX_TITLE_CHARS,
    CrawlCancelled,
    classify_content_type,
    classify_url,
    is_same_site,
    normalize_url,
    path_allowed,
    resolve_href,
    url_file_name,
)

log = logging.getLogger(__name__)

REMOVED_TAGS = ['script', 'style', 'noscript', 'template', 'svg', 'iframe', 'nav', 'header', 'footer', 'form', 'aside']


@dataclass
class ParsedLink:
    url: str
    text: str
    context: str


@dataclass
class ParsedPage:
    title: str
    canonical: Optional[str]
    links: list[ParsedLink]
    text: str


def _clean(value: str) -> str:
    return ' '.join((value or '').split())


def parse_html_page(html: str, page_url: str) -> ParsedPage:
    soup = BeautifulSoup(html, 'lxml')

    base_tag = soup.find('base', href=True)
    base_url = urljoin(page_url, base_tag['href']) if base_tag else page_url

    title = _clean(soup.title.string) if soup.title and soup.title.string else ''
    if not title:
        og_title = soup.find('meta', attrs={'property': 'og:title'})
        if og_title and og_title.get('content'):
            title = _clean(og_title['content'])
    if not title:
        h1 = soup.find('h1')
        if h1:
            title = _clean(h1.get_text(' ', strip=True))
    title = title[:MAX_TITLE_CHARS]

    canonical = None
    for link_tag in soup.find_all('link', href=True):
        rel = link_tag.get('rel') or []
        if isinstance(rel, str):
            rel = rel.split()
        if 'canonical' in [value.lower() for value in rel]:
            canonical = resolve_href(page_url, link_tag['href'])
            break

    links: list[ParsedLink] = []
    seen_on_page: set[str] = set()
    for anchor in soup.find_all('a', href=True):
        url = resolve_href(base_url, anchor['href'])
        if not url or url in seen_on_page:
            continue
        seen_on_page.add(url)
        text = _clean(anchor.get_text(' ', strip=True))[:MAX_LINK_TEXT_CHARS]
        parent = anchor.find_parent(['p', 'li', 'td', 'dd', 'figcaption', 'div'])
        context = _clean(parent.get_text(' ', strip=True))[:MAX_CONTEXT_CHARS] if parent else ''
        links.append(ParsedLink(url=url, text=text, context=context))

    for tag in soup(REMOVED_TAGS):
        tag.decompose()
    root = soup.find('main') or soup.find('article') or soup.body or soup
    lines = [_clean(line) for line in root.get_text('\n').splitlines()]
    text = '\n'.join(line for line in lines if line)[:MAX_PAGE_TEXT_CHARS]

    return ParsedPage(title=title, canonical=canonical, links=links, text=text)


def decode_html(body: bytes, content_type: str) -> str:
    charset = 'utf-8'
    for part in (content_type or '').split(';')[1:]:
        key, _, value = part.strip().partition('=')
        if key.lower() == 'charset' and value:
            charset = value.strip('"\' ').lower()
    try:
        return body.decode(charset, errors='replace')
    except LookupError:
        return body.decode('utf-8', errors='replace')


def new_item(
    kind: str,
    url: str,
    *,
    title: Optional[str] = None,
    name: Optional[str] = None,
    file_type: Optional[str] = None,
    size: Optional[int] = None,
    depth: int = 0,
    found_on: Optional[str] = None,
    found_on_title: Optional[str] = None,
    link_text: Optional[str] = None,
    context: Optional[str] = None,
    status: str = 'ok',
    http_status: Optional[int] = None,
    content_text: Optional[str] = None,
) -> dict:
    return {
        'kind': kind,
        'url': url,
        'title': title,
        'name': name,
        'file_type': file_type or None,
        'size': size,
        'depth': depth,
        'found_on': found_on,
        'found_on_title': found_on_title,
        'link_text': link_text or None,
        'context': context or None,
        'status': status,
        'http_status': http_status,
        'selected': False,
        'content_text': content_text,
        'extract_status': None,
        'extract_error': None,
    }


def is_selectable(item: dict) -> bool:
    return (item['kind'] == 'page' and item['status'] == 'ok') or (
        item['kind'] == 'file' and item['status'] == 'supported'
    )


class WidgetCrawler:
    def __init__(self, run_id: str, settings: ChatWidgetCrawlSettings, cancel_event: asyncio.Event):
        self.run_id = run_id
        self.settings = settings
        self.cancel_event = cancel_event
        self.start_url = settings.start_url
        self.max_total_bytes = settings.max_total_size_mb * 1024 * 1024
        self.max_file_bytes = settings.max_file_size_mb * 1024 * 1024
        self.delay_seconds = settings.request_delay_ms / 1000
        self.items: dict[str, dict] = {}
        self.seen: set[str] = set()
        self.files_to_probe: list[str] = []
        self.pages_attempted = 0
        self.linked_count = 0
        self.error_count = 0
        self.bytes_downloaded = 0
        self.limit_reached: Optional[str] = None
        self.phase = 'starting'
        self.queued = 0
        self.fetcher: Optional[CrawlFetcher] = None

    @property
    def progress(self) -> dict:
        counts = {'page': 0, 'file': 0, 'resource': 0, 'error': 0}
        for item in self.items.values():
            counts[item['kind']] += 1
        return {
            'phase': self.phase,
            'pages': counts['page'],
            'files': counts['file'],
            'resources': counts['resource'],
            'errors': counts['error'],
            'pages_attempted': self.pages_attempted,
            'queued': self.queued,
            'bytes_downloaded': self.bytes_downloaded,
            'limit_reached': self.limit_reached,
        }

    def check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise CrawlCancelled()

    async def save_progress(self) -> None:
        if await ChatWidgetCrawlRuns.update_progress(self.run_id, self.progress):
            self.cancel_event.set()
        self.check_cancel()

    def set_limit(self, name: str) -> None:
        if self.limit_reached is None:
            self.limit_reached = name

    async def crawl(self) -> None:
        async with CrawlFetcher(self.settings.request_timeout) as fetcher:
            self.fetcher = fetcher

            sitemap_entries: list[tuple[str, str]] = []
            if self.settings.follow_sitemap and self.settings.max_depth >= 1:
                self.phase = 'sitemap'
                await self.save_progress()
                sitemap_entries = await self.discover_sitemap_urls()

            self.phase = 'pages'
            self.seen.add(self.start_url)
            level: list[tuple[str, Optional[str], Optional[str]]] = [(self.start_url, None, None)]
            depth = 0
            while level and depth <= self.settings.max_depth:
                self.check_cancel()
                self.queued = len(level)
                await self.save_progress()

                semaphore = asyncio.Semaphore(self.settings.max_concurrency)

                async def crawl_entry(entry, entry_depth=depth):
                    async with semaphore:
                        links, fetched = await self.crawl_page(entry, entry_depth)
                        if fetched and self.delay_seconds:
                            await asyncio.sleep(self.delay_seconds)
                        return links

                next_level = []
                for links in await asyncio.gather(*(crawl_entry(entry) for entry in level)):
                    next_level.extend(links)

                if depth == 0:
                    for sitemap_url, page_url in sitemap_entries:
                        candidate = self.handle_link(page_url, 1, sitemap_url, 'Sitemap', '', '')
                        if candidate:
                            next_level.append(candidate)

                level = next_level
                depth += 1

            self.queued = 0
            if self.settings.discover_files and self.files_to_probe:
                self.phase = 'files'
                await self.save_progress()
                await self.probe_files()

            self.phase = 'saving'
            await self.save_progress()

    async def discover_sitemap_urls(self) -> list[tuple[str, str]]:
        parts = urlsplit(self.start_url)
        origin = f'{parts.scheme}://{parts.netloc}'
        queue = [f'{origin}/sitemap.xml']
        robots = await self.fetcher.get_robots(origin)
        if robots:
            for sitemap in robots.site_maps() or []:
                normalized = normalize_url(sitemap)
                if normalized and normalized not in queue:
                    queue.append(normalized)

        entries: list[tuple[str, str]] = []
        visited: set[str] = set()
        while queue and len(visited) < MAX_SITEMAPS and len(entries) < MAX_SITEMAP_URLS:
            self.check_cancel()
            sitemap_url = queue.pop(0)
            if sitemap_url in visited:
                continue
            visited.add(sitemap_url)

            result = await self.fetcher.fetch(sitemap_url, max_bytes=MAX_SITEMAP_BYTES)
            self.bytes_downloaded += len(result.body)
            if result.status != 'ok':
                continue

            soup = await asyncio.to_thread(BeautifulSoup, result.body, 'xml')
            for sitemap_tag in soup.find_all('sitemap'):
                loc = sitemap_tag.find('loc')
                normalized = normalize_url(loc.get_text(strip=True)) if loc else None
                if normalized and normalized not in visited:
                    queue.append(normalized)
            for url_tag in soup.find_all('url'):
                loc = url_tag.find('loc')
                normalized = normalize_url(loc.get_text(strip=True)) if loc else None
                if normalized:
                    entries.append((sitemap_url, normalized))
                if len(entries) >= MAX_SITEMAP_URLS:
                    break
        return entries

    def handle_link(
        self,
        url: str,
        depth: int,
        found_on: str,
        found_on_title: str,
        link_text: str,
        context: str,
    ) -> Optional[tuple[str, str, str]]:
        """Record a discovered link. Returns a page entry to crawl next, or None."""
        if url in self.seen:
            return None

        kind, type_value = classify_url(url, self.settings.allowed_file_types)
        if kind == 'page':
            if depth > self.settings.max_depth:
                return None
            if self.settings.same_domain_only and not is_same_site(url, self.start_url):
                return None
            if not path_allowed(url, self.settings.include_paths, self.settings.exclude_paths):
                return None
            self.seen.add(url)
            return (url, found_on, found_on_title)

        if not self.settings.discover_files:
            return None
        self.seen.add(url)
        self.add_linked_item(kind, type_value, url, depth, found_on, found_on_title, link_text, context)
        if kind == 'file' and url in self.items:
            self.files_to_probe.append(url)
        return None

    def add_linked_item(
        self,
        kind: str,
        type_value: str,
        url: str,
        depth: int,
        found_on: Optional[str],
        found_on_title: Optional[str],
        link_text: str,
        context: str,
        size: Optional[int] = None,
    ) -> None:
        if not self.settings.discover_files:
            return
        if self.linked_count >= MAX_LINKED_ITEMS:
            self.set_limit('max_linked_items')
            return
        self.linked_count += 1

        status = 'ok'
        if kind == 'file':
            status = 'too_large' if size is not None and size > self.max_file_bytes else 'supported'

        self.items[url] = new_item(
            kind,
            url,
            name=url_file_name(url),
            file_type=type_value,
            size=size,
            depth=depth,
            found_on=found_on,
            found_on_title=found_on_title,
            link_text=link_text,
            context=context,
            status=status,
        )

    def add_error(
        self,
        url: str,
        status: str,
        http_status: Optional[int],
        depth: int,
        found_on: Optional[str],
        found_on_title: Optional[str],
    ) -> None:
        if self.error_count >= MAX_ERROR_ITEMS:
            return
        self.error_count += 1
        self.items[url] = new_item(
            'error',
            url,
            name=url_file_name(url),
            depth=depth,
            found_on=found_on,
            found_on_title=found_on_title,
            status=status,
            http_status=http_status,
        )

    async def crawl_page(self, entry: tuple[str, Optional[str], Optional[str]], depth: int) -> tuple[list, bool]:
        """Crawl one page. Returns (next page entries, whether an HTTP request was made)."""
        url, found_on, found_on_title = entry
        self.check_cancel()

        if self.pages_attempted >= self.settings.max_pages:
            self.set_limit('max_pages')
            return [], False
        if self.bytes_downloaded >= self.max_total_bytes:
            self.set_limit('max_total_size')
            return [], False

        self.pages_attempted += 1
        if self.pages_attempted % 10 == 0:
            await self.save_progress()

        if self.settings.respect_robots and not await self.fetcher.robots_allows(url):
            self.add_error(url, 'robots_disallowed', None, depth, found_on, found_on_title)
            return [], False

        result = await self.fetcher.fetch(url, max_bytes=MAX_PAGE_BYTES)
        self.bytes_downloaded += len(result.body)
        if result.status != 'ok':
            self.add_error(url, result.status, result.http_status, depth, found_on, found_on_title)
            return [], True

        final_url = result.url
        if final_url != url:
            if final_url in self.seen:
                return [], True
            if self.settings.same_domain_only and not is_same_site(final_url, self.start_url):
                self.add_error(url, 'redirect_off_site', result.http_status, depth, found_on, found_on_title)
                return [], True
            self.seen.add(final_url)

        kind, type_value = classify_content_type(
            result.content_type, final_url, self.settings.allowed_file_types, result.body[:1024]
        )
        if kind != 'page':
            self.add_linked_item(
                kind, type_value, final_url, depth, found_on, found_on_title, '', '', size=result.content_length
            )
            return [], True

        html = decode_html(result.body, result.content_type)
        page = await asyncio.to_thread(parse_html_page, html, final_url)

        if page.canonical and page.canonical != final_url and is_same_site(page.canonical, final_url):
            if page.canonical in self.seen:
                return [], True
            self.seen.add(page.canonical)
            final_url = page.canonical

        title = page.title or final_url
        self.items[final_url] = new_item(
            'page',
            final_url,
            title=title,
            size=len(result.body),
            depth=depth,
            found_on=found_on,
            found_on_title=found_on_title,
            status='ok',
            http_status=result.http_status,
            content_text=page.text,
        )

        candidates = []
        for link in page.links:
            candidate = self.handle_link(link.url, depth + 1, final_url, title, link.text, link.context)
            if candidate:
                candidates.append(candidate)
        return candidates, True

    async def probe_files(self) -> None:
        semaphore = asyncio.Semaphore(self.settings.max_concurrency)

        async def probe(url: str) -> None:
            async with semaphore:
                self.check_cancel()
                await self.probe_file(url)
                if self.delay_seconds:
                    await asyncio.sleep(self.delay_seconds)

        await asyncio.gather(*(probe(url) for url in self.files_to_probe))

    async def probe_file(self, url: str) -> None:
        item = self.items[url]
        if self.settings.respect_robots and not await self.fetcher.robots_allows(url):
            item['status'] = 'robots_disallowed'
            return

        result = await self.fetcher.fetch(url, method='HEAD')
        if result.status == 'http_error' and result.http_status in (403, 405, 501):
            result = await self.fetcher.fetch(url, method='GET', read_body=False)

        if result.status != 'ok':
            item['kind'] = 'error'
            item['status'] = result.status
            item['http_status'] = result.http_status
            return

        base_content_type = result.content_type.split(';')[0].strip().lower()
        if base_content_type in HTML_CONTENT_TYPES:
            item['status'] = 'not_a_file'
            return

        item['size'] = result.content_length
        if result.content_length is not None and result.content_length > self.max_file_bytes:
            item['status'] = 'too_large'

    def build_items(self, previous_selection: dict[tuple[str, str], bool]) -> list[dict]:
        items = []
        for item in self.items.values():
            item['selected'] = is_selectable(item) and previous_selection.get((item['kind'], item['url']), True)
            items.append(item)
        return items


async def run_crawl(run_id: str, cancel_event: asyncio.Event) -> None:
    run = await ChatWidgetCrawlRuns.get_run_by_id(run_id)
    if not run:
        return

    crawler = WidgetCrawler(run.id, run.settings, cancel_event)
    try:
        await ChatWidgetCrawlRuns.mark_running(run.id)
        await crawler.crawl()

        previous_run = await ChatWidgetCrawlRuns.get_latest_completed_run(run.widget_id, exclude_run_id=run.id)
        previous_selection = await ChatWidgetCrawlItems.get_selection_map(previous_run.id) if previous_run else {}
        await ChatWidgetCrawlItems.insert_items(run.id, run.widget_id, crawler.build_items(previous_selection))

        crawler.phase = 'done'
        await ChatWidgetCrawlRuns.finish_run(run.id, 'completed', crawler.progress)
        await ChatWidgetCrawlRuns.delete_old_runs(run.widget_id, KEEP_RUNS_PER_WIDGET)
    except CrawlCancelled:
        await ChatWidgetCrawlRuns.finish_run(run.id, 'cancelled', crawler.progress)
    except Exception as e:
        log.exception('Widget crawl %s failed', run.id)
        await ChatWidgetCrawlRuns.finish_run(run.id, 'failed', crawler.progress, error=(str(e) or 'Crawl failed')[:1000])
