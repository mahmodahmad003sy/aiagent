"""Pure helpers for the widget website crawler: constants, URL normalization, classification and filters."""

from __future__ import annotations

import os
import re
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

CRAWLER_USER_AGENT = 'OpenWebUI-WidgetCrawler/1.0'
CRAWLER_ROBOTS_TOKEN = 'OpenWebUI-WidgetCrawler'

MAX_REDIRECTS = 5
MAX_PAGE_BYTES = 5 * 1024 * 1024
MAX_ROBOTS_BYTES = 512 * 1024
MAX_SITEMAP_BYTES = 5 * 1024 * 1024
MAX_SITEMAPS = 10
MAX_SITEMAP_URLS = 5000
MAX_LINKED_ITEMS = 2000
MAX_ERROR_ITEMS = 500
MAX_PAGE_TEXT_CHARS = 200_000
MIN_PAGE_TEXT_CHARS = 30
MAX_LINK_TEXT_CHARS = 200
MAX_CONTEXT_CHARS = 300
MAX_TITLE_CHARS = 300
KEEP_RUNS_PER_WIDGET = 3
HEARTBEAT_INTERVAL_SECONDS = 30
STALE_JOB_SECONDS = 120
STALE_JOB_ERROR = 'The job stopped unexpectedly. Please start it again.'

SUPPORTED_FILE_TYPES = ('pdf', 'docx', 'xlsx', 'csv', 'txt', 'pptx')
PAGE_EXTENSIONS = {'', 'html', 'htm', 'xhtml', 'shtml', 'php', 'asp', 'aspx', 'jsp', 'cfm'}
HTML_CONTENT_TYPES = {'text/html', 'application/xhtml+xml'}

CONTENT_TYPE_TO_FILE_TYPE = {
    'application/pdf': 'pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx',
    'text/csv': 'csv',
    'text/plain': 'txt',
}
FILE_TYPE_TO_CONTENT_TYPE = {file_type: content_type for content_type, file_type in CONTENT_TYPE_TO_FILE_TYPE.items()}

RESOURCE_TYPE_LABELS = {
    **{ext: 'Archive' for ext in ('zip', 'rar', '7z', 'tar', 'gz', 'tgz', 'bz2', 'xz')},
    **{ext: 'Image' for ext in ('png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'ico', 'tif', 'tiff', 'avif')},
    **{ext: 'Video' for ext in ('mp4', 'mov', 'avi', 'mkv', 'webm', 'wmv', 'm4v')},
    **{ext: 'Audio' for ext in ('mp3', 'wav', 'ogg', 'flac', 'm4a', 'aac')},
    **{ext: 'Executable' for ext in ('exe', 'msi', 'dmg', 'apk', 'deb', 'rpm', 'bin')},
    **{ext: 'Document' for ext in ('doc', 'xls', 'ppt', 'rtf', 'odt', 'ods', 'odp', 'epub')},
}

TRACKING_PARAMS = {'gclid', 'fbclid', 'msclkid', 'mc_cid', 'mc_eid', '_ga', '_gl', 'yclid', 'igshid'}
SKIP_HREF_PREFIXES = ('mailto:', 'tel:', 'javascript:', 'data:', 'sms:', 'ftp:', '#')


class CrawlCancelled(Exception):
    """Raised inside crawl/extend jobs when the admin cancelled the job."""


def normalize_url(url: str | None) -> str | None:
    """Return a canonical http(s) URL, or None if the URL is not crawlable."""
    if not url:
        return None
    url = url.strip()
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None

    scheme = parts.scheme.lower()
    if scheme not in ('http', 'https'):
        return None

    host = (parts.hostname or '').lower().rstrip('.')
    if not host:
        return None
    netloc = f'[{host}]' if ':' in host else host
    if port and not ((scheme == 'http' and port == 80) or (scheme == 'https' and port == 443)):
        netloc = f'{netloc}:{port}'

    path = parts.path or '/'
    if path != '/' and path.endswith('/'):
        path = path.rstrip('/') or '/'

    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith('utm_') and key.lower() not in TRACKING_PARAMS
    ]
    query_pairs.sort()
    query = urlencode(query_pairs, doseq=True)

    return urlunsplit((scheme, netloc, path, query, ''))


def resolve_href(base_url: str, href: str | None) -> str | None:
    if not href:
        return None
    href = href.strip()
    if not href or href.lower().startswith(SKIP_HREF_PREFIXES):
        return None
    return normalize_url(urljoin(base_url, href))


def site_host(url: str) -> str:
    host = (urlsplit(url).hostname or '').lower()
    return host[4:] if host.startswith('www.') else host


def is_same_site(url: str, start_url: str) -> bool:
    return site_host(url) == site_host(start_url)


def url_extension(url: str) -> str:
    name = urlsplit(url).path.rsplit('/', 1)[-1]
    ext = os.path.splitext(name)[1][1:].lower()
    if ext.isdigit() or len(ext) > 5:
        return ''
    return ext


def url_file_name(url: str) -> str:
    name = unquote(urlsplit(url).path.rsplit('/', 1)[-1])
    return name or site_host(url) or url


def resource_type_label(ext: str) -> str:
    return RESOURCE_TYPE_LABELS.get(ext, ext.upper() if ext else 'Other')


def _label_from_content_type(base_content_type: str) -> str:
    if base_content_type.startswith('image/'):
        return 'Image'
    if base_content_type.startswith('video/'):
        return 'Video'
    if base_content_type.startswith('audio/'):
        return 'Audio'
    if base_content_type in ('application/zip', 'application/x-tar', 'application/gzip', 'application/x-7z-compressed'):
        return 'Archive'
    return 'Other'


def classify_url(url: str, allowed_file_types: list[str]) -> tuple[str, str]:
    """Classify by URL extension. Returns (kind, type) with kind in page/file/resource."""
    ext = url_extension(url)
    if ext in PAGE_EXTENSIONS:
        return 'page', ''
    if ext in SUPPORTED_FILE_TYPES and ext in allowed_file_types:
        return 'file', ext
    return 'resource', resource_type_label(ext)


def classify_content_type(
    content_type: str, url: str, allowed_file_types: list[str], body_start: bytes = b''
) -> tuple[str, str]:
    """Classify a fetched response by its Content-Type header. Returns (kind, type)."""
    base = (content_type or '').split(';')[0].strip().lower()
    if base in HTML_CONTENT_TYPES:
        return 'page', ''
    if not base:
        sample = body_start[:1024].lstrip().lower()
        if sample.startswith((b'<!doctype html', b'<html')) or b'<html' in sample:
            return 'page', ''
        kind, type_value = classify_url(url, allowed_file_types)
        return ('resource', 'Other') if kind == 'page' else (kind, type_value)
    file_type = CONTENT_TYPE_TO_FILE_TYPE.get(base)
    if file_type and file_type in allowed_file_types:
        return 'file', file_type
    ext = url_extension(url)
    return 'resource', resource_type_label(ext) if ext else _label_from_content_type(base)


def path_allowed(url: str, include_paths: list[str], exclude_paths: list[str]) -> bool:
    path = urlsplit(url).path or '/'
    if any(path.startswith(prefix) for prefix in exclude_paths):
        return False
    if include_paths and not any(path.startswith(prefix) for prefix in include_paths):
        return False
    return True


def slugify(value: str, max_length: int = 80) -> str:
    value = re.sub(r'[^\w.-]+', '-', value or '').strip('-._')
    return value[:max_length].rstrip('-._') or 'item'


def human_size(size: int | None) -> str:
    if size is None:
        return 'unknown'
    value = float(size)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if value < 1024 or unit == 'GB':
            return f'{value:.0f} {unit}' if unit == 'B' else f'{value:.1f} {unit}'
        value /= 1024
    return f'{size} B'


def render_resource_text(
    *,
    name: str,
    type_label: str,
    url: str,
    found_on: str | None,
    found_on_title: str | None,
    link_text: str | None,
    context: str | None,
    size: int | None,
) -> str:
    lines = [
        'Downloadable resource (link only)',
        f'Name: {name}',
        f'Type: {type_label}',
        f'URL: {url}',
    ]
    if found_on:
        lines.append(f'Found on page: {found_on_title or found_on} ({found_on})')
    if link_text:
        lines.append(f'Link text: {link_text}')
    if context:
        lines.append(f'Context: {context}')
    lines.append(f'Size: {human_size(size)}')
    lines.append(
        'Note: The contents of this file were NOT read or indexed. Do not describe what is inside it. '
        'Tell the user the resource exists and give them the URL and the page where it was found.'
    )
    return '\n'.join(lines)
