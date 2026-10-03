# Website Crawl → Widget Knowledge — Technical Implementation Plan

**Source requirements:** `website-crawl-knowledge-plan.md`
**Branch:** `widget`
**Audience:** implementing developer

---

## 0. Rules for the implementer (read first)

1. Implement **exactly** what is written here. Do not rename anything, add features, change limits, change labels, or "improve" the design. If something seems wrong or missing, **stop and ask** — do not decide yourself.
2. Do the tasks **in order** (T1 → T16). Each task lists the files it touches and an "Done when" check.
3. Do **not** add new Python or npm dependencies. Everything used here (`aiohttp`, `beautifulsoup4`, `lxml`, `urllib.robotparser`) already exists.
4. Do **not** touch locale/translation files. Use `$i18n.t('...')` with the English text exactly as written.
5. Backend code style: single quotes, 120 columns. After finishing, run `ruff format <each changed .py file>` (only the files you changed, not the whole repo).
6. Frontend code style: run `npx prettier --write <each changed .ts/.svelte file>` (only the files you changed).
7. Where this document gives full code, copy it **as-is**. Where it gives an edit, apply exactly that edit and nothing else.

---

## 1. Design decisions (already decided — do not change)

| Topic | Decision |
|---|---|
| Crawl settings storage | One row per widget in `chat_widget_crawl_config`; all settings in one JSON column `settings`, validated by the Pydantic model `ChatWidgetCrawlSettings`. |
| Runs | Every crawl creates a row in `chat_widget_crawl_run`. The run stores a **snapshot** of the settings. Only the **3 newest** runs per widget are kept. |
| Results | Discovered URLs are stored in `chat_widget_crawl_item` with `kind` = `page` / `file` / `resource` / `error`. |
| Page text | Page text is extracted **during the crawl** and stored in `chat_widget_crawl_item.content_text` (max 200,000 chars). Nothing is embedded during the crawl. |
| Knowledge state | What is currently in the widget knowledge is tracked in a 4th table `chat_widget_knowledge_item` (one row per `(widget_id, kind, url)`), so sync works across runs. |
| Knowledge base | Each widget gets **one** normal Open WebUI Knowledge base, created on first "Extend Knowledge", stored in new column `chat_widget.knowledge_id`. |
| Documents in knowledge | Every page, file and resource becomes **one Open WebUI File** inside that knowledge base. Pages and resources are uploaded as `.txt` files; supported files are uploaded with their original bytes. Upload/extract/chunk/embed reuse `upload_file_handler` from `routers/files.py` with `metadata.knowledge_id`. |
| Chat | Public widget chat sends `files: [{'type': 'collection', 'id': widget.knowledge_id}]` so the normal RAG pipeline is used. |
| Background jobs | `asyncio.create_task` + a DB heartbeat. DB is the source of truth for "is a job running". Cancel works through a DB flag (`cancel_requested`) so it works with several workers. A job whose heartbeat is older than 120 s is marked failed. |
| One job at a time | Per widget, only one crawl **or** one extend job can be active. |
| JavaScript sites | Not supported (no headless browser). UI shows a notice. |
| SSRF | Every request goes through `validate_url()` and `get_ssrf_safe_session()` from `retrieval/web/utils.py`. Redirects are followed **manually** (max 5) and each hop is validated. Environment proxies are **disabled** for the crawler (`trust_env=False`). |
| Cancel during crawl | A cancelled crawl stores **no** items. Previous results stay visible. |
| Path filters | Plain **prefix** match on the URL path (no wildcards). Applies to **pages only**. The start URL is always crawled. |
| Same-domain | Compares hosts with a leading `www.` removed. Applies to **pages only**. Files/resources linked from crawled pages are recorded regardless of their domain. |
| Permissions | Only the widget owner (`get_verified_user` + `user_id` match) can use the crawl endpoints. Creating the widget knowledge base does **not** require the `workspace.knowledge` permission. |

### Deviations from `website-crawl-knowledge-plan.md` data model
- `chat_widget_crawl_config` stores settings in one JSON column instead of one column per setting.
- Max file size / total size are stored in **MB** (`max_file_size_mb`, `max_total_size_mb`).
- Extra table `chat_widget_knowledge_item` (needed for sync across runs).
- `knowledge_file_id` is in `chat_widget_knowledge_item.file_id`, not in the crawl item.

---

## 2. File map

### New files
| # | File |
|---|---|
| T2 | `backend/open_webui/utils/widget_crawl_urls.py` |
| T3 | `backend/open_webui/models/chat_widget_crawl.py` |
| T4 | `backend/open_webui/migrations/versions/a1c4e7b9d2f3_chat_widget_crawl.py` |
| T5 | `backend/open_webui/utils/widget_crawl_fetch.py` |
| T6 | `backend/open_webui/utils/widget_crawler.py` |
| T7 | `backend/open_webui/utils/widget_knowledge_sync.py` |
| T8 | `backend/open_webui/utils/widget_crawl_jobs.py` |
| T9 | `backend/open_webui/routers/widget_crawl.py` |
| T13 | `src/lib/apis/widgets/crawl.ts` |
| T14 | `src/lib/components/workspace/WidgetCrawl.svelte` |

### Modified files
| # | File |
|---|---|
| T1 | `backend/open_webui/models/chat_widgets.py` |
| T10 | `backend/open_webui/main.py` |
| T11 | `backend/open_webui/routers/widgets.py` (public chat) |
| T12 | `backend/open_webui/routers/widgets.py` (widget delete) |
| T15 | `src/lib/apis/widgets/index.ts` |
| T16 | `src/lib/components/workspace/ChatWidgets.svelte` |

---

## T1 — Add `knowledge_id` to the widget model

**File:** `backend/open_webui/models/chat_widgets.py`

1. In class `ChatWidget(Base)`, add this line **directly after** `folder_id = Column(Text, nullable=True)`:
   ```python
       knowledge_id = Column(Text, nullable=True)
   ```
2. In class `ChatWidgetModel(BaseModel)`, add this line **directly after** `folder_id: Optional[str] = None`:
   ```python
       knowledge_id: Optional[str] = None
   ```
3. Do **not** add `knowledge_id` to `ChatWidgetForm` or `ChatWidgetUpdateForm` (users must not set it).
4. In class `ChatWidgetTable`, add this method **directly after** `set_folder_id`:
   ```python
       async def set_knowledge_id(
           self, id: str, knowledge_id: Optional[str], db: Optional[AsyncSession] = None
       ) -> None:
           async with get_async_db_context(db) as db:
               widget = await db.get(ChatWidget, id)
               if widget:
                   widget.knowledge_id = knowledge_id
                   await db.commit()
   ```

**Done when:** the file imports without errors (`python -c "import open_webui.models.chat_widgets"` from `backend/`).

---

## T2 — URL helpers and constants

**File (new):** `backend/open_webui/utils/widget_crawl_urls.py` — copy exactly:

```python
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
```

**Done when:** `python -c "from open_webui.utils.widget_crawl_urls import normalize_url; print(normalize_url('HTTPS://WWW.Example.com:443/a/?utm_source=x&b=2#top'))"` prints `https://www.example.com/a?b=2`.

---

## T3 — Database models

**File (new):** `backend/open_webui/models/chat_widget_crawl.py` — copy exactly:

```python
"""Website crawl data for chat widgets: settings, runs, discovered items and synced knowledge items."""

from __future__ import annotations

import time
import uuid
from typing import Literal, Optional

from open_webui.internal.db import Base, get_async_db_context
from open_webui.utils.widget_crawl_urls import STALE_JOB_ERROR, STALE_JOB_SECONDS, SUPPORTED_FILE_TYPES, normalize_url
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    and_,
    delete,
    func,
    or_,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

ACTIVE_STATUSES = ('pending', 'running')
CrawlFileType = Literal['pdf', 'docx', 'xlsx', 'csv', 'txt', 'pptx']


def _normalize_paths(value: list[str] | None) -> list[str]:
    paths = []
    for raw in value or []:
        path = (raw or '').strip()
        if not path:
            continue
        if not path.startswith('/'):
            raise ValueError(f'Path must start with "/": {path}')
        if len(path) > 200:
            raise ValueError('Paths can be at most 200 characters')
        if path not in paths:
            paths.append(path)
    if len(paths) > 50:
        raise ValueError('At most 50 paths are allowed')
    return paths


####################
# Settings
####################


class ChatWidgetCrawlSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')

    start_url: str = Field(min_length=1, max_length=2048)
    max_depth: int = Field(default=2, ge=0, le=5)
    max_pages: int = Field(default=100, ge=1, le=1000)
    same_domain_only: bool = True
    follow_sitemap: bool = True
    respect_robots: bool = True
    discover_files: bool = True
    include_paths: list[str] = Field(default_factory=list)
    exclude_paths: list[str] = Field(default_factory=list)
    allowed_file_types: list[CrawlFileType] = Field(default_factory=lambda: list(SUPPORTED_FILE_TYPES))
    max_file_size_mb: int = Field(default=20, ge=1, le=100)
    max_total_size_mb: int = Field(default=500, ge=10, le=5000)
    request_timeout: int = Field(default=20, ge=5, le=120)
    request_delay_ms: int = Field(default=500, ge=0, le=10000)
    max_concurrency: int = Field(default=2, ge=1, le=5)

    @field_validator('start_url')
    @classmethod
    def validate_start_url(cls, value: str) -> str:
        normalized = normalize_url(value)
        if not normalized:
            raise ValueError('Website URL must be a valid http(s) URL')
        return normalized

    @field_validator('include_paths', 'exclude_paths')
    @classmethod
    def validate_paths(cls, value: list[str]) -> list[str]:
        return _normalize_paths(value)

    @field_validator('allowed_file_types')
    @classmethod
    def order_file_types(cls, value: list[str]) -> list[str]:
        return [file_type for file_type in SUPPORTED_FILE_TYPES if file_type in value]


####################
# Tables
####################


class ChatWidgetCrawlConfig(Base):
    __tablename__ = 'chat_widget_crawl_config'

    id = Column(Text, primary_key=True)
    widget_id = Column(Text, ForeignKey('chat_widget.id', ondelete='CASCADE'), nullable=False)
    settings = Column(JSON, nullable=False)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    __table_args__ = (Index('ix_chat_widget_crawl_config_widget_id', 'widget_id', unique=True),)


class ChatWidgetCrawlRun(Base):
    __tablename__ = 'chat_widget_crawl_run'

    id = Column(Text, primary_key=True)
    widget_id = Column(Text, ForeignKey('chat_widget.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(Text, nullable=False)
    settings = Column(JSON, nullable=False)
    status = Column(Text, nullable=False)
    progress = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    cancel_requested = Column(Boolean, nullable=False, default=False)
    heartbeat_at = Column(BigInteger, nullable=True)
    started_at = Column(BigInteger, nullable=True)
    finished_at = Column(BigInteger, nullable=True)
    extend_status = Column(Text, nullable=True)
    extend_progress = Column(JSON, nullable=True)
    extend_error = Column(Text, nullable=True)
    extend_started_at = Column(BigInteger, nullable=True)
    extend_finished_at = Column(BigInteger, nullable=True)
    created_at = Column(BigInteger, nullable=False)

    __table_args__ = (Index('ix_chat_widget_crawl_run_widget_created', 'widget_id', 'created_at'),)


class ChatWidgetCrawlItem(Base):
    __tablename__ = 'chat_widget_crawl_item'

    id = Column(Text, primary_key=True)
    run_id = Column(Text, ForeignKey('chat_widget_crawl_run.id', ondelete='CASCADE'), nullable=False)
    widget_id = Column(Text, nullable=False)
    kind = Column(Text, nullable=False)
    url = Column(Text, nullable=False)
    title = Column(Text, nullable=True)
    name = Column(Text, nullable=True)
    file_type = Column(Text, nullable=True)
    size = Column(BigInteger, nullable=True)
    depth = Column(Integer, nullable=True)
    found_on = Column(Text, nullable=True)
    found_on_title = Column(Text, nullable=True)
    link_text = Column(Text, nullable=True)
    context = Column(Text, nullable=True)
    status = Column(Text, nullable=False)
    http_status = Column(Integer, nullable=True)
    selected = Column(Boolean, nullable=False, default=False)
    content_text = Column(Text, nullable=True)
    extract_status = Column(Text, nullable=True)
    extract_error = Column(Text, nullable=True)
    created_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        Index('ix_chat_widget_crawl_item_run_kind', 'run_id', 'kind'),
        Index('ix_chat_widget_crawl_item_widget_id', 'widget_id'),
    )


class ChatWidgetKnowledgeItem(Base):
    __tablename__ = 'chat_widget_knowledge_item'

    id = Column(Text, primary_key=True)
    widget_id = Column(Text, ForeignKey('chat_widget.id', ondelete='CASCADE'), nullable=False)
    kind = Column(Text, nullable=False)
    url = Column(Text, nullable=False)
    file_id = Column(Text, nullable=False)
    content_hash = Column(Text, nullable=False)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint('widget_id', 'kind', 'url', name='uq_chat_widget_knowledge_item_widget_kind_url'),
        Index('ix_chat_widget_knowledge_item_widget_id', 'widget_id'),
    )


####################
# Pydantic models
####################


class ChatWidgetCrawlConfigModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    widget_id: str
    settings: ChatWidgetCrawlSettings
    created_at: int
    updated_at: int


class ChatWidgetCrawlRunModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    widget_id: str
    user_id: str
    settings: ChatWidgetCrawlSettings
    status: str
    progress: dict = Field(default_factory=dict)
    error: Optional[str] = None
    cancel_requested: bool = False
    heartbeat_at: Optional[int] = None
    started_at: Optional[int] = None
    finished_at: Optional[int] = None
    extend_status: Optional[str] = None
    extend_progress: dict = Field(default_factory=dict)
    extend_error: Optional[str] = None
    extend_started_at: Optional[int] = None
    extend_finished_at: Optional[int] = None
    created_at: int

    @field_validator('progress', 'extend_progress', mode='before')
    @classmethod
    def default_dict(cls, value):
        return value or {}


class ChatWidgetCrawlItemResponse(BaseModel):
    """Crawl item as returned by the API (without the stored page text)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    kind: str
    url: str
    title: Optional[str] = None
    name: Optional[str] = None
    file_type: Optional[str] = None
    size: Optional[int] = None
    depth: Optional[int] = None
    found_on: Optional[str] = None
    found_on_title: Optional[str] = None
    link_text: Optional[str] = None
    context: Optional[str] = None
    status: str
    http_status: Optional[int] = None
    selected: bool = False
    extract_status: Optional[str] = None
    extract_error: Optional[str] = None


class ChatWidgetCrawlItemModel(ChatWidgetCrawlItemResponse):
    content_text: Optional[str] = None


class ChatWidgetKnowledgeItemModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    widget_id: str
    kind: str
    url: str
    file_id: str
    content_hash: str
    created_at: int
    updated_at: int


def _selectable_clause():
    return or_(
        and_(ChatWidgetCrawlItem.kind == 'page', ChatWidgetCrawlItem.status == 'ok'),
        and_(ChatWidgetCrawlItem.kind == 'file', ChatWidgetCrawlItem.status == 'supported'),
    )


####################
# Table operations
####################


class ChatWidgetCrawlConfigTable:
    async def get_by_widget_id(
        self, widget_id: str, db: Optional[AsyncSession] = None
    ) -> Optional[ChatWidgetCrawlConfigModel]:
        async with get_async_db_context(db) as db:
            result = await db.execute(select(ChatWidgetCrawlConfig).filter_by(widget_id=widget_id))
            config = result.scalars().first()
            return ChatWidgetCrawlConfigModel.model_validate(config) if config else None

    async def upsert(
        self, widget_id: str, settings: ChatWidgetCrawlSettings, db: Optional[AsyncSession] = None
    ) -> ChatWidgetCrawlConfigModel:
        async with get_async_db_context(db) as db:
            now = int(time.time())
            result = await db.execute(select(ChatWidgetCrawlConfig).filter_by(widget_id=widget_id))
            config = result.scalars().first()
            if config:
                config.settings = settings.model_dump()
                config.updated_at = now
            else:
                config = ChatWidgetCrawlConfig(
                    id=str(uuid.uuid4()),
                    widget_id=widget_id,
                    settings=settings.model_dump(),
                    created_at=now,
                    updated_at=now,
                )
                db.add(config)
            await db.commit()
            await db.refresh(config)
            return ChatWidgetCrawlConfigModel.model_validate(config)

    async def delete_by_widget_id(self, widget_id: str, db: Optional[AsyncSession] = None) -> None:
        async with get_async_db_context(db) as db:
            await db.execute(delete(ChatWidgetCrawlConfig).where(ChatWidgetCrawlConfig.widget_id == widget_id))
            await db.commit()


class ChatWidgetCrawlRunTable:
    async def _update(self, id: str, values: dict, db: Optional[AsyncSession] = None) -> Optional[ChatWidgetCrawlRunModel]:
        async with get_async_db_context(db) as db:
            await db.execute(update(ChatWidgetCrawlRun).where(ChatWidgetCrawlRun.id == id).values(**values))
            await db.commit()
            result = await db.execute(
                select(ChatWidgetCrawlRun)
                .where(ChatWidgetCrawlRun.id == id)
                .execution_options(populate_existing=True)
            )
            run = result.scalars().first()
            return ChatWidgetCrawlRunModel.model_validate(run) if run else None

    async def create_run(
        self, widget_id: str, user_id: str, settings: ChatWidgetCrawlSettings, db: Optional[AsyncSession] = None
    ) -> ChatWidgetCrawlRunModel:
        async with get_async_db_context(db) as db:
            now = int(time.time())
            run = ChatWidgetCrawlRun(
                id=str(uuid.uuid4()),
                widget_id=widget_id,
                user_id=user_id,
                settings=settings.model_dump(),
                status='pending',
                progress={},
                cancel_requested=False,
                heartbeat_at=now,
                created_at=now,
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            return ChatWidgetCrawlRunModel.model_validate(run)

    async def get_run_by_id(self, id: str, db: Optional[AsyncSession] = None) -> Optional[ChatWidgetCrawlRunModel]:
        async with get_async_db_context(db) as db:
            result = await db.execute(
                select(ChatWidgetCrawlRun)
                .where(ChatWidgetCrawlRun.id == id)
                .execution_options(populate_existing=True)
            )
            run = result.scalars().first()
            return ChatWidgetCrawlRunModel.model_validate(run) if run else None

    async def get_run_by_id_and_widget_id(
        self, id: str, widget_id: str, db: Optional[AsyncSession] = None
    ) -> Optional[ChatWidgetCrawlRunModel]:
        async with get_async_db_context(db) as db:
            result = await db.execute(select(ChatWidgetCrawlRun).filter_by(id=id, widget_id=widget_id))
            run = result.scalars().first()
            return ChatWidgetCrawlRunModel.model_validate(run) if run else None

    async def get_latest_run(self, widget_id: str, db: Optional[AsyncSession] = None) -> Optional[ChatWidgetCrawlRunModel]:
        async with get_async_db_context(db) as db:
            result = await db.execute(
                select(ChatWidgetCrawlRun)
                .filter_by(widget_id=widget_id)
                .order_by(ChatWidgetCrawlRun.created_at.desc())
                .limit(1)
            )
            run = result.scalars().first()
            return ChatWidgetCrawlRunModel.model_validate(run) if run else None

    async def get_latest_completed_run(
        self, widget_id: str, exclude_run_id: Optional[str] = None, db: Optional[AsyncSession] = None
    ) -> Optional[ChatWidgetCrawlRunModel]:
        async with get_async_db_context(db) as db:
            query = select(ChatWidgetCrawlRun).filter_by(widget_id=widget_id, status='completed')
            if exclude_run_id:
                query = query.where(ChatWidgetCrawlRun.id != exclude_run_id)
            result = await db.execute(query.order_by(ChatWidgetCrawlRun.created_at.desc()).limit(1))
            run = result.scalars().first()
            return ChatWidgetCrawlRunModel.model_validate(run) if run else None

    async def get_active_run(self, widget_id: str, db: Optional[AsyncSession] = None) -> Optional[ChatWidgetCrawlRunModel]:
        async with get_async_db_context(db) as db:
            result = await db.execute(
                select(ChatWidgetCrawlRun)
                .where(
                    ChatWidgetCrawlRun.widget_id == widget_id,
                    or_(
                        ChatWidgetCrawlRun.status.in_(ACTIVE_STATUSES),
                        ChatWidgetCrawlRun.extend_status.in_(ACTIVE_STATUSES),
                    ),
                )
                .limit(1)
            )
            run = result.scalars().first()
            return ChatWidgetCrawlRunModel.model_validate(run) if run else None

    async def expire_stale_runs(self, widget_id: str, db: Optional[AsyncSession] = None) -> None:
        async with get_async_db_context(db) as db:
            now = int(time.time())
            stale = or_(
                ChatWidgetCrawlRun.heartbeat_at.is_(None),
                ChatWidgetCrawlRun.heartbeat_at < now - STALE_JOB_SECONDS,
            )
            await db.execute(
                update(ChatWidgetCrawlRun)
                .where(
                    ChatWidgetCrawlRun.widget_id == widget_id,
                    ChatWidgetCrawlRun.status.in_(ACTIVE_STATUSES),
                    stale,
                )
                .values(status='failed', error=STALE_JOB_ERROR, finished_at=now)
            )
            await db.execute(
                update(ChatWidgetCrawlRun)
                .where(
                    ChatWidgetCrawlRun.widget_id == widget_id,
                    ChatWidgetCrawlRun.extend_status.in_(ACTIVE_STATUSES),
                    stale,
                )
                .values(extend_status='failed', extend_error=STALE_JOB_ERROR, extend_finished_at=now)
            )
            await db.commit()

    async def mark_running(self, id: str) -> None:
        now = int(time.time())
        await self._update(id, {'status': 'running', 'started_at': now, 'heartbeat_at': now})

    async def update_progress(self, id: str, progress: dict) -> bool:
        """Save progress. Returns True when the admin requested cancel."""
        run = await self._update(id, {'progress': progress, 'heartbeat_at': int(time.time())})
        return bool(run and run.cancel_requested)

    async def finish_run(self, id: str, status: str, progress: dict, error: Optional[str] = None) -> None:
        await self._update(
            id,
            {
                'status': status,
                'progress': progress,
                'error': error,
                'finished_at': int(time.time()),
                'cancel_requested': False,
            },
        )

    async def request_cancel(self, id: str, db: Optional[AsyncSession] = None) -> None:
        await self._update(id, {'cancel_requested': True}, db=db)

    async def start_extend(self, id: str, db: Optional[AsyncSession] = None) -> Optional[ChatWidgetCrawlRunModel]:
        now = int(time.time())
        return await self._update(
            id,
            {
                'extend_status': 'running',
                'extend_progress': {},
                'extend_error': None,
                'extend_started_at': now,
                'extend_finished_at': None,
                'cancel_requested': False,
                'heartbeat_at': now,
            },
            db=db,
        )

    async def update_extend_progress(self, id: str, progress: dict) -> bool:
        """Save extend progress. Returns True when the admin requested cancel."""
        run = await self._update(id, {'extend_progress': progress, 'heartbeat_at': int(time.time())})
        return bool(run and run.cancel_requested)

    async def finish_extend(self, id: str, status: str, progress: dict, error: Optional[str] = None) -> None:
        await self._update(
            id,
            {
                'extend_status': status,
                'extend_progress': progress,
                'extend_error': error,
                'extend_finished_at': int(time.time()),
                'cancel_requested': False,
            },
        )

    async def touch_heartbeat(self, id: str) -> None:
        await self._update(id, {'heartbeat_at': int(time.time())})

    async def delete_old_runs(self, widget_id: str, keep: int) -> None:
        async with get_async_db_context() as db:
            result = await db.execute(
                select(ChatWidgetCrawlRun.id)
                .where(ChatWidgetCrawlRun.widget_id == widget_id)
                .order_by(ChatWidgetCrawlRun.created_at.desc())
                .offset(keep)
            )
            old_ids = list(result.scalars().all())
            if not old_ids:
                return
            await db.execute(delete(ChatWidgetCrawlItem).where(ChatWidgetCrawlItem.run_id.in_(old_ids)))
            await db.execute(delete(ChatWidgetCrawlRun).where(ChatWidgetCrawlRun.id.in_(old_ids)))
            await db.commit()

    async def delete_runs_by_widget_id(self, widget_id: str, db: Optional[AsyncSession] = None) -> None:
        async with get_async_db_context(db) as db:
            await db.execute(delete(ChatWidgetCrawlItem).where(ChatWidgetCrawlItem.widget_id == widget_id))
            await db.execute(delete(ChatWidgetCrawlRun).where(ChatWidgetCrawlRun.widget_id == widget_id))
            await db.commit()


class ChatWidgetCrawlItemTable:
    async def insert_items(self, run_id: str, widget_id: str, items: list[dict]) -> None:
        async with get_async_db_context() as db:
            now = int(time.time())
            db.add_all(
                [
                    ChatWidgetCrawlItem(id=str(uuid.uuid4()), run_id=run_id, widget_id=widget_id, created_at=now, **item)
                    for item in items
                ]
            )
            await db.commit()

    async def get_items_by_run_id(self, run_id: str) -> list[ChatWidgetCrawlItemModel]:
        async with get_async_db_context() as db:
            result = await db.execute(
                select(ChatWidgetCrawlItem)
                .where(ChatWidgetCrawlItem.run_id == run_id)
                .order_by(ChatWidgetCrawlItem.kind, ChatWidgetCrawlItem.depth, ChatWidgetCrawlItem.url)
            )
            return [ChatWidgetCrawlItemModel.model_validate(item) for item in result.scalars().all()]

    async def get_item_responses_by_run_id(
        self, run_id: str, db: Optional[AsyncSession] = None
    ) -> list[ChatWidgetCrawlItemResponse]:
        async with get_async_db_context(db) as db:
            result = await db.execute(
                select(ChatWidgetCrawlItem)
                .where(ChatWidgetCrawlItem.run_id == run_id)
                .options(defer(ChatWidgetCrawlItem.content_text))
                .order_by(ChatWidgetCrawlItem.kind, ChatWidgetCrawlItem.depth, ChatWidgetCrawlItem.url)
            )
            return [ChatWidgetCrawlItemResponse.model_validate(item) for item in result.scalars().all()]

    async def get_selection_map(self, run_id: str) -> dict[tuple[str, str], bool]:
        async with get_async_db_context() as db:
            result = await db.execute(
                select(ChatWidgetCrawlItem.kind, ChatWidgetCrawlItem.url, ChatWidgetCrawlItem.selected).where(
                    ChatWidgetCrawlItem.run_id == run_id
                )
            )
            return {(kind, url): bool(selected) for kind, url, selected in result.all()}

    async def get_summary(self, run_id: str, db: Optional[AsyncSession] = None) -> dict:
        async with get_async_db_context(db) as db:
            result = await db.execute(
                select(
                    ChatWidgetCrawlItem.kind,
                    ChatWidgetCrawlItem.status,
                    ChatWidgetCrawlItem.selected,
                    func.count(),
                )
                .where(ChatWidgetCrawlItem.run_id == run_id)
                .group_by(ChatWidgetCrawlItem.kind, ChatWidgetCrawlItem.status, ChatWidgetCrawlItem.selected)
            )
            summary = {
                'pages': 0,
                'files': 0,
                'resources': 0,
                'errors': 0,
                'selected_pages': 0,
                'selectable_pages': 0,
                'selected_files': 0,
                'selectable_files': 0,
            }
            for kind, status, selected, count in result.all():
                if kind == 'page':
                    summary['pages'] += count
                    if status == 'ok':
                        summary['selectable_pages'] += count
                        if selected:
                            summary['selected_pages'] += count
                elif kind == 'file':
                    summary['files'] += count
                    if status == 'supported':
                        summary['selectable_files'] += count
                        if selected:
                            summary['selected_files'] += count
                elif kind == 'resource':
                    summary['resources'] += count
                elif kind == 'error':
                    summary['errors'] += count
            return summary

    async def set_selected(
        self,
        run_id: str,
        selected: bool,
        item_ids: Optional[list[str]] = None,
        kind: Optional[str] = None,
        db: Optional[AsyncSession] = None,
    ) -> int:
        async with get_async_db_context(db) as db:
            query = update(ChatWidgetCrawlItem).where(ChatWidgetCrawlItem.run_id == run_id, _selectable_clause())
            if item_ids is not None:
                query = query.where(ChatWidgetCrawlItem.id.in_(item_ids))
            if kind is not None:
                query = query.where(ChatWidgetCrawlItem.kind == kind)
            result = await db.execute(query.values(selected=selected))
            await db.commit()
            return result.rowcount or 0

    async def set_extract_status(self, item_id: str, extract_status: Optional[str], extract_error: Optional[str]) -> None:
        async with get_async_db_context() as db:
            await db.execute(
                update(ChatWidgetCrawlItem)
                .where(ChatWidgetCrawlItem.id == item_id)
                .values(extract_status=extract_status, extract_error=extract_error)
            )
            await db.commit()

    async def clear_extract_status(self, run_id: str) -> None:
        async with get_async_db_context() as db:
            await db.execute(
                update(ChatWidgetCrawlItem)
                .where(ChatWidgetCrawlItem.run_id == run_id)
                .values(extract_status=None, extract_error=None)
            )
            await db.commit()


class ChatWidgetKnowledgeItemTable:
    async def get_items_by_widget_id(
        self, widget_id: str, db: Optional[AsyncSession] = None
    ) -> list[ChatWidgetKnowledgeItemModel]:
        async with get_async_db_context(db) as db:
            result = await db.execute(select(ChatWidgetKnowledgeItem).filter_by(widget_id=widget_id))
            return [ChatWidgetKnowledgeItemModel.model_validate(item) for item in result.scalars().all()]

    async def count_items_by_widget_id(self, widget_id: str, db: Optional[AsyncSession] = None) -> int:
        async with get_async_db_context(db) as db:
            result = await db.execute(
                select(func.count()).select_from(ChatWidgetKnowledgeItem).filter_by(widget_id=widget_id)
            )
            return int(result.scalar() or 0)

    async def upsert_item(self, widget_id: str, kind: str, url: str, file_id: str, content_hash: str) -> None:
        async with get_async_db_context() as db:
            now = int(time.time())
            result = await db.execute(select(ChatWidgetKnowledgeItem).filter_by(widget_id=widget_id, kind=kind, url=url))
            item = result.scalars().first()
            if item:
                item.file_id = file_id
                item.content_hash = content_hash
                item.updated_at = now
            else:
                db.add(
                    ChatWidgetKnowledgeItem(
                        id=str(uuid.uuid4()),
                        widget_id=widget_id,
                        kind=kind,
                        url=url,
                        file_id=file_id,
                        content_hash=content_hash,
                        created_at=now,
                        updated_at=now,
                    )
                )
            await db.commit()

    async def delete_item(self, id: str) -> None:
        async with get_async_db_context() as db:
            await db.execute(delete(ChatWidgetKnowledgeItem).where(ChatWidgetKnowledgeItem.id == id))
            await db.commit()

    async def delete_items_by_widget_id(self, widget_id: str, db: Optional[AsyncSession] = None) -> None:
        async with get_async_db_context(db) as db:
            await db.execute(delete(ChatWidgetKnowledgeItem).where(ChatWidgetKnowledgeItem.widget_id == widget_id))
            await db.commit()


ChatWidgetCrawlConfigs = ChatWidgetCrawlConfigTable()
ChatWidgetCrawlRuns = ChatWidgetCrawlRunTable()
ChatWidgetCrawlItems = ChatWidgetCrawlItemTable()
ChatWidgetKnowledgeItems = ChatWidgetKnowledgeItemTable()
```

**Done when:** `python -c "import open_webui.models.chat_widget_crawl"` works.

---

## T4 — Migration

**File (new):** `backend/open_webui/migrations/versions/a1c4e7b9d2f3_chat_widget_crawl.py` — copy exactly:

```python
"""chat widget website crawl

Revision ID: a1c4e7b9d2f3
Revises: 7c2e9a41b5d3
Create Date: 2026-10-03 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1c4e7b9d2f3'
down_revision: str | None = '7c2e9a41b5d3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = set(inspector.get_table_names())

    if 'chat_widget' in tables:
        columns = {column['name'] for column in inspector.get_columns('chat_widget')}
        if 'knowledge_id' not in columns:
            with op.batch_alter_table('chat_widget') as batch_op:
                batch_op.add_column(sa.Column('knowledge_id', sa.Text(), nullable=True))

    if 'chat_widget_crawl_config' not in tables:
        op.create_table(
            'chat_widget_crawl_config',
            sa.Column('id', sa.Text(), primary_key=True),
            sa.Column('widget_id', sa.Text(), sa.ForeignKey('chat_widget.id', ondelete='CASCADE'), nullable=False),
            sa.Column('settings', sa.JSON(), nullable=False),
            sa.Column('created_at', sa.BigInteger(), nullable=False),
            sa.Column('updated_at', sa.BigInteger(), nullable=False),
        )
        op.create_index(
            'ix_chat_widget_crawl_config_widget_id', 'chat_widget_crawl_config', ['widget_id'], unique=True
        )

    if 'chat_widget_crawl_run' not in tables:
        op.create_table(
            'chat_widget_crawl_run',
            sa.Column('id', sa.Text(), primary_key=True),
            sa.Column('widget_id', sa.Text(), sa.ForeignKey('chat_widget.id', ondelete='CASCADE'), nullable=False),
            sa.Column('user_id', sa.Text(), nullable=False),
            sa.Column('settings', sa.JSON(), nullable=False),
            sa.Column('status', sa.Text(), nullable=False),
            sa.Column('progress', sa.JSON(), nullable=True),
            sa.Column('error', sa.Text(), nullable=True),
            sa.Column('cancel_requested', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('heartbeat_at', sa.BigInteger(), nullable=True),
            sa.Column('started_at', sa.BigInteger(), nullable=True),
            sa.Column('finished_at', sa.BigInteger(), nullable=True),
            sa.Column('extend_status', sa.Text(), nullable=True),
            sa.Column('extend_progress', sa.JSON(), nullable=True),
            sa.Column('extend_error', sa.Text(), nullable=True),
            sa.Column('extend_started_at', sa.BigInteger(), nullable=True),
            sa.Column('extend_finished_at', sa.BigInteger(), nullable=True),
            sa.Column('created_at', sa.BigInteger(), nullable=False),
        )
        op.create_index(
            'ix_chat_widget_crawl_run_widget_created', 'chat_widget_crawl_run', ['widget_id', 'created_at']
        )

    if 'chat_widget_crawl_item' not in tables:
        op.create_table(
            'chat_widget_crawl_item',
            sa.Column('id', sa.Text(), primary_key=True),
            sa.Column(
                'run_id', sa.Text(), sa.ForeignKey('chat_widget_crawl_run.id', ondelete='CASCADE'), nullable=False
            ),
            sa.Column('widget_id', sa.Text(), nullable=False),
            sa.Column('kind', sa.Text(), nullable=False),
            sa.Column('url', sa.Text(), nullable=False),
            sa.Column('title', sa.Text(), nullable=True),
            sa.Column('name', sa.Text(), nullable=True),
            sa.Column('file_type', sa.Text(), nullable=True),
            sa.Column('size', sa.BigInteger(), nullable=True),
            sa.Column('depth', sa.Integer(), nullable=True),
            sa.Column('found_on', sa.Text(), nullable=True),
            sa.Column('found_on_title', sa.Text(), nullable=True),
            sa.Column('link_text', sa.Text(), nullable=True),
            sa.Column('context', sa.Text(), nullable=True),
            sa.Column('status', sa.Text(), nullable=False),
            sa.Column('http_status', sa.Integer(), nullable=True),
            sa.Column('selected', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('content_text', sa.Text(), nullable=True),
            sa.Column('extract_status', sa.Text(), nullable=True),
            sa.Column('extract_error', sa.Text(), nullable=True),
            sa.Column('created_at', sa.BigInteger(), nullable=False),
        )
        op.create_index('ix_chat_widget_crawl_item_run_kind', 'chat_widget_crawl_item', ['run_id', 'kind'])
        op.create_index('ix_chat_widget_crawl_item_widget_id', 'chat_widget_crawl_item', ['widget_id'])

    if 'chat_widget_knowledge_item' not in tables:
        op.create_table(
            'chat_widget_knowledge_item',
            sa.Column('id', sa.Text(), primary_key=True),
            sa.Column('widget_id', sa.Text(), sa.ForeignKey('chat_widget.id', ondelete='CASCADE'), nullable=False),
            sa.Column('kind', sa.Text(), nullable=False),
            sa.Column('url', sa.Text(), nullable=False),
            sa.Column('file_id', sa.Text(), nullable=False),
            sa.Column('content_hash', sa.Text(), nullable=False),
            sa.Column('created_at', sa.BigInteger(), nullable=False),
            sa.Column('updated_at', sa.BigInteger(), nullable=False),
            sa.UniqueConstraint('widget_id', 'kind', 'url', name='uq_chat_widget_knowledge_item_widget_kind_url'),
        )
        op.create_index('ix_chat_widget_knowledge_item_widget_id', 'chat_widget_knowledge_item', ['widget_id'])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = set(inspector.get_table_names())

    if 'chat_widget_knowledge_item' in tables:
        op.drop_index('ix_chat_widget_knowledge_item_widget_id', table_name='chat_widget_knowledge_item')
        op.drop_table('chat_widget_knowledge_item')

    if 'chat_widget_crawl_item' in tables:
        op.drop_index('ix_chat_widget_crawl_item_widget_id', table_name='chat_widget_crawl_item')
        op.drop_index('ix_chat_widget_crawl_item_run_kind', table_name='chat_widget_crawl_item')
        op.drop_table('chat_widget_crawl_item')

    if 'chat_widget_crawl_run' in tables:
        op.drop_index('ix_chat_widget_crawl_run_widget_created', table_name='chat_widget_crawl_run')
        op.drop_table('chat_widget_crawl_run')

    if 'chat_widget_crawl_config' in tables:
        op.drop_index('ix_chat_widget_crawl_config_widget_id', table_name='chat_widget_crawl_config')
        op.drop_table('chat_widget_crawl_config')

    if 'chat_widget' in tables:
        columns = {column['name'] for column in inspector.get_columns('chat_widget')}
        if 'knowledge_id' in columns:
            with op.batch_alter_table('chat_widget') as batch_op:
                batch_op.drop_column('knowledge_id')
```

**Done when:** starting the backend runs the migration with no error, and the 4 new tables + `chat_widget.knowledge_id` exist in the DB.

---

## T5 — Safe HTTP fetcher (SSRF, redirects, robots.txt)

**File (new):** `backend/open_webui/utils/widget_crawl_fetch.py` — copy exactly:

```python
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
```

**Done when:** the module imports without errors.

---

## T6 — Crawl job

**File (new):** `backend/open_webui/utils/widget_crawler.py` — copy exactly:

```python
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
```

**Done when:** the module imports without errors.

---

## T7 — Extend Knowledge job (sync)

**File (new):** `backend/open_webui/utils/widget_knowledge_sync.py` — copy exactly:

```python
"""Extend Knowledge job: syncs the selected crawl results into the widget's knowledge base."""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
from typing import Optional

from fastapi import HTTPException, Request, UploadFile
from open_webui.internal.db import get_async_db
from open_webui.models.chat_widget_crawl import (
    ChatWidgetCrawlItemModel,
    ChatWidgetCrawlItems,
    ChatWidgetCrawlRunModel,
    ChatWidgetCrawlRuns,
    ChatWidgetKnowledgeItemModel,
    ChatWidgetKnowledgeItems,
)
from open_webui.models.chat_widgets import ChatWidgetModel, ChatWidgets
from open_webui.models.files import Files
from open_webui.models.knowledge import KnowledgeForm, Knowledges
from open_webui.models.users import Users
from open_webui.retrieval.vector.async_client import ASYNC_VECTOR_DB_CLIENT
from open_webui.utils.widget_crawl_fetch import CrawlFetcher
from open_webui.utils.widget_crawl_urls import (
    FILE_TYPE_TO_CONTENT_TYPE,
    MIN_PAGE_TEXT_CHARS,
    CrawlCancelled,
    render_resource_text,
    slugify,
    url_file_name,
)
from starlette.datastructures import Headers

log = logging.getLogger(__name__)

NO_TEXT_MESSAGE = 'No extractable text found'


class SyncItemSkipped(Exception):
    def __init__(self, outcome: str, message: str, remove_existing: bool):
        super().__init__(message)
        self.outcome = outcome
        self.message = message
        self.remove_existing = remove_existing


async def remove_knowledge_file(knowledge_id: str, file_id: str) -> None:
    """Remove one file from the widget knowledge base, its vectors and the file itself."""
    from open_webui.routers.knowledge import delete_file_resource

    await Knowledges.remove_file_from_knowledge_by_id(knowledge_id=knowledge_id, file_id=file_id)
    try:
        await ASYNC_VECTOR_DB_CLIENT.delete(collection_name=knowledge_id, filter={'file_id': file_id})
    except Exception as e:
        log.debug('Vector delete failed for file %s: %s', file_id, e)

    file = await Files.get_file_by_id(file_id)
    if file:
        async with get_async_db() as db:
            await delete_file_resource(file, db)


async def ensure_widget_knowledge(widget: ChatWidgetModel, owner) -> str:
    if widget.knowledge_id:
        knowledge = await Knowledges.get_knowledge_by_id(widget.knowledge_id)
        if knowledge:
            return knowledge.id

    knowledge = await Knowledges.insert_new_knowledge(
        owner.id,
        KnowledgeForm(
            name=f'Widget: {widget.name} (website)'[:100],
            description=(
                f'Managed automatically by chat widget "{widget.name}" ({widget.id}). '
                'Changes made here are overwritten by Extend Knowledge.'
            ),
            access_grants=[],
        ),
    )
    if not knowledge:
        raise RuntimeError('Could not create the widget knowledge base')

    await Knowledges.update_knowledge_meta_by_id(knowledge.id, {'managed_by': 'chat_widget', 'widget_id': widget.id})
    await ChatWidgets.set_knowledge_id(widget.id, knowledge.id)
    await ChatWidgetKnowledgeItems.delete_items_by_widget_id(widget.id)
    return knowledge.id


async def delete_widget_knowledge(widget_id: str, knowledge_id: str) -> None:
    """Delete the widget-managed knowledge base and the files the widget created. Used when a widget is deleted."""
    from open_webui.routers.knowledge import delete_file_resource

    knowledge = await Knowledges.get_knowledge_by_id(knowledge_id)
    if not knowledge or (knowledge.meta or {}).get('widget_id') != widget_id:
        return

    for file in await Knowledges.get_files_by_id(knowledge_id):
        if ((file.meta or {}).get('data') or {}).get('widget_id') != widget_id:
            continue
        async with get_async_db() as db:
            await delete_file_resource(file, db)

    try:
        await ASYNC_VECTOR_DB_CLIENT.delete_collection(collection_name=knowledge_id)
    except Exception as e:
        log.debug('Vector collection delete failed for %s: %s', knowledge_id, e)

    await Knowledges.delete_knowledge_by_id(knowledge_id)


async def add_document_to_knowledge(
    request: Request,
    owner,
    knowledge_id: str,
    widget_id: str,
    item: ChatWidgetCrawlItemModel,
    filename: str,
    content_type: str,
    data: bytes,
) -> tuple[Optional[str], str, Optional[str]]:
    """Upload, extract, embed and link one document. Returns (file_id, outcome, error)."""
    from open_webui.routers.files import upload_file_handler

    upload = UploadFile(
        file=io.BytesIO(data),
        filename=filename,
        headers=Headers({'content-type': content_type}),
    )
    try:
        uploaded = await upload_file_handler(
            request,
            file=upload,
            metadata={
                'knowledge_id': knowledge_id,
                'source_url': item.url,
                'widget_id': widget_id,
                'widget_crawl_kind': item.kind,
            },
            process=True,
            process_in_background=False,
            user=owner,
        )
    except HTTPException as e:
        return None, 'failed', str(e.detail)

    file_id = uploaded.get('id') if isinstance(uploaded, dict) else getattr(uploaded, 'id', None)
    if not file_id:
        return None, 'failed', 'Upload failed'

    file = await Files.get_file_by_id(file_id)
    file_data = (file.data or {}) if file else {}
    if not (file_data.get('content') or '').strip():
        await remove_knowledge_file(knowledge_id, file_id)
        return None, 'no_text', NO_TEXT_MESSAGE

    if file_data.get('status') == 'failed' or not await Knowledges.has_file(knowledge_id, file_id):
        await remove_knowledge_file(knowledge_id, file_id)
        return None, 'failed', str(file_data.get('error') or 'Processing failed')[:1000]

    return file_id, 'embedded', None


class KnowledgeSync:
    def __init__(
        self,
        request: Request,
        run: ChatWidgetCrawlRunModel,
        widget: ChatWidgetModel,
        owner,
        cancel_event: asyncio.Event,
    ):
        self.request = request
        self.run = run
        self.widget = widget
        self.owner = owner
        self.cancel_event = cancel_event
        self.max_file_bytes = run.settings.max_file_size_mb * 1024 * 1024
        self.max_total_bytes = run.settings.max_total_size_mb * 1024 * 1024
        self.bytes_downloaded = 0
        self.progress = {
            'total': 0,
            'done': 0,
            'embedded': 0,
            'unchanged': 0,
            'removed': 0,
            'no_text': 0,
            'failed': 0,
            'skipped_limit': 0,
        }

    def check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise CrawlCancelled()

    async def save_progress(self) -> None:
        if await ChatWidgetCrawlRuns.update_extend_progress(self.run.id, self.progress):
            self.cancel_event.set()
        self.check_cancel()

    async def run_sync(self) -> None:
        knowledge_id = await ensure_widget_knowledge(self.widget, self.owner)
        await ChatWidgetCrawlItems.clear_extract_status(self.run.id)

        desired: dict[tuple[str, str], ChatWidgetCrawlItemModel] = {}
        for item in await ChatWidgetCrawlItems.get_items_by_run_id(self.run.id):
            if (
                (item.kind == 'page' and item.status == 'ok' and item.selected)
                or (item.kind == 'file' and item.status == 'supported' and item.selected)
                or (item.kind == 'resource' and item.status == 'ok')
            ):
                desired[(item.kind, item.url)] = item

        existing: dict[tuple[str, str], ChatWidgetKnowledgeItemModel] = {
            (knowledge_item.kind, knowledge_item.url): knowledge_item
            for knowledge_item in await ChatWidgetKnowledgeItems.get_items_by_widget_id(self.widget.id)
        }

        self.progress['total'] = len(desired)
        await self.save_progress()

        for key, knowledge_item in existing.items():
            if key in desired:
                continue
            self.check_cancel()
            await remove_knowledge_file(knowledge_id, knowledge_item.file_id)
            await ChatWidgetKnowledgeItems.delete_item(knowledge_item.id)
            self.progress['removed'] += 1
        await self.save_progress()

        async with CrawlFetcher(self.run.settings.request_timeout) as fetcher:
            for key, item in desired.items():
                self.check_cancel()
                outcome, error = await self.sync_item(fetcher, knowledge_id, item, existing.get(key))
                await ChatWidgetCrawlItems.set_extract_status(item.id, outcome, error)
                self.progress[outcome] += 1
                self.progress['done'] += 1
                await self.save_progress()

    async def sync_item(
        self,
        fetcher: CrawlFetcher,
        knowledge_id: str,
        item: ChatWidgetCrawlItemModel,
        existing: Optional[ChatWidgetKnowledgeItemModel],
    ) -> tuple[str, Optional[str]]:
        try:
            filename, content_type, data = await self.build_document(fetcher, item)
        except SyncItemSkipped as skipped:
            if existing and skipped.remove_existing:
                await remove_knowledge_file(knowledge_id, existing.file_id)
                await ChatWidgetKnowledgeItems.delete_item(existing.id)
            return skipped.outcome, skipped.message

        content_hash = hashlib.sha256(data).hexdigest()
        if (
            existing
            and existing.content_hash == content_hash
            and await Knowledges.has_file(knowledge_id, existing.file_id)
        ):
            return 'unchanged', None

        file_id, outcome, error = await add_document_to_knowledge(
            self.request, self.owner, knowledge_id, self.widget.id, item, filename, content_type, data
        )

        if outcome == 'no_text' and existing:
            await remove_knowledge_file(knowledge_id, existing.file_id)
            await ChatWidgetKnowledgeItems.delete_item(existing.id)
        if outcome != 'embedded':
            return outcome, error

        if existing:
            await remove_knowledge_file(knowledge_id, existing.file_id)
        await ChatWidgetKnowledgeItems.upsert_item(self.widget.id, item.kind, item.url, file_id, content_hash)
        return 'embedded', None

    async def build_document(self, fetcher: CrawlFetcher, item: ChatWidgetCrawlItemModel) -> tuple[str, str, bytes]:
        if item.kind == 'page':
            text = (item.content_text or '').strip()
            if len(text) < MIN_PAGE_TEXT_CHARS:
                raise SyncItemSkipped('no_text', NO_TEXT_MESSAGE, True)
            title = item.title or item.url
            document = f'Title: {title}\nURL: {item.url}\n\n{text}'
            return f'{slugify(title)}.txt', 'text/plain', document.encode('utf-8')

        if item.kind == 'resource':
            name = item.name or url_file_name(item.url)
            document = render_resource_text(
                name=name,
                type_label=item.file_type or 'Other',
                url=item.url,
                found_on=item.found_on,
                found_on_title=item.found_on_title,
                link_text=item.link_text,
                context=item.context,
                size=item.size,
            )
            return f'resource-{slugify(name)}.txt', 'text/plain', document.encode('utf-8')

        if self.bytes_downloaded >= self.max_total_bytes:
            raise SyncItemSkipped('skipped_limit', 'Maximum total download size reached', False)

        result = await fetcher.fetch(item.url, max_bytes=self.max_file_bytes)
        self.bytes_downloaded += len(result.body)
        if result.status == 'too_large':
            raise SyncItemSkipped('failed', 'File is larger than the maximum file size', False)
        if result.status != 'ok':
            detail = f'Download failed: {result.status}'
            if result.http_status:
                detail = f'{detail} (HTTP {result.http_status})'
            raise SyncItemSkipped('failed', detail, False)

        file_type = item.file_type or 'txt'
        base_content_type = result.content_type.split(';')[0].strip().lower()
        if not base_content_type or base_content_type in ('application/octet-stream', 'binary/octet-stream'):
            base_content_type = FILE_TYPE_TO_CONTENT_TYPE[file_type]
        stem = os.path.splitext(item.name or url_file_name(item.url))[0]
        return f'{slugify(stem)}.{file_type}', base_content_type, result.body


async def run_extend(request: Request, run_id: str, cancel_event: asyncio.Event) -> None:
    run = await ChatWidgetCrawlRuns.get_run_by_id(run_id)
    if not run:
        return

    sync: Optional[KnowledgeSync] = None
    try:
        widget = await ChatWidgets.get_widget_by_id(run.widget_id)
        owner = await Users.get_user_by_id(widget.user_id) if widget else None
        if not widget or not owner:
            raise RuntimeError('Widget or widget owner not found')

        sync = KnowledgeSync(request, run, widget, owner, cancel_event)
        await sync.run_sync()
        await ChatWidgetCrawlRuns.finish_extend(run.id, 'completed', sync.progress)
    except CrawlCancelled:
        await ChatWidgetCrawlRuns.finish_extend(run.id, 'cancelled', sync.progress if sync else {})
    except Exception as e:
        log.exception('Widget extend knowledge %s failed', run.id)
        await ChatWidgetCrawlRuns.finish_extend(
            run.id, 'failed', sync.progress if sync else {}, error=(str(e) or 'Extend Knowledge failed')[:1000]
        )
```

**Done when:** the module imports without errors.

---

## T8 — Job registry

**File (new):** `backend/open_webui/utils/widget_crawl_jobs.py` — copy exactly:

```python
"""In-process registry for widget crawl / extend background jobs. The database stays the source of truth."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from open_webui.models.chat_widget_crawl import ChatWidgetCrawlRuns
from open_webui.utils.widget_crawl_urls import HEARTBEAT_INTERVAL_SECONDS

log = logging.getLogger(__name__)


@dataclass
class WidgetJob:
    widget_id: str
    run_id: str
    kind: str  # crawl | extend
    cancel_event: asyncio.Event
    task: Optional[asyncio.Task] = None


_jobs: dict[str, WidgetJob] = {}

# Serialises "is a job active?" + "start job" inside this process.
job_start_lock = asyncio.Lock()


async def _heartbeat(run_id: str) -> None:
    while True:
        try:
            await ChatWidgetCrawlRuns.touch_heartbeat(run_id)
        except Exception as e:
            log.warning('Widget crawl heartbeat failed for %s: %s', run_id, e)
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)


def start_job(
    widget_id: str,
    run_id: str,
    kind: str,
    runner: Callable[[asyncio.Event], Awaitable[None]],
) -> WidgetJob:
    job = WidgetJob(widget_id=widget_id, run_id=run_id, kind=kind, cancel_event=asyncio.Event())

    async def wrapper() -> None:
        heartbeat = asyncio.create_task(_heartbeat(run_id))
        try:
            await runner(job.cancel_event)
        finally:
            heartbeat.cancel()
            if _jobs.get(widget_id) is job:
                _jobs.pop(widget_id, None)

    _jobs[widget_id] = job
    job.task = asyncio.create_task(wrapper())
    return job


def request_cancel(widget_id: str) -> None:
    job = _jobs.get(widget_id)
    if job:
        job.cancel_event.set()
```

**Done when:** the module imports without errors.

---

## T9 — API router

**File (new):** `backend/open_webui/routers/widget_crawl.py` — copy exactly:

```python
"""Owner-only API for widget website crawling and Extend Knowledge."""

from __future__ import annotations

import asyncio
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.internal.db import get_async_session
from open_webui.models.chat_widget_crawl import (
    ACTIVE_STATUSES,
    ChatWidgetCrawlConfigModel,
    ChatWidgetCrawlConfigs,
    ChatWidgetCrawlItemResponse,
    ChatWidgetCrawlItems,
    ChatWidgetCrawlRunModel,
    ChatWidgetCrawlRuns,
    ChatWidgetCrawlSettings,
    ChatWidgetKnowledgeItems,
)
from open_webui.models.chat_widgets import ChatWidgetModel, ChatWidgets
from open_webui.retrieval.web.utils import validate_url
from open_webui.utils.auth import get_verified_user
from open_webui.utils.widget_crawl_jobs import job_start_lock, request_cancel, start_job
from open_webui.utils.widget_crawler import run_crawl
from open_webui.utils.widget_knowledge_sync import run_extend
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()

JOB_ALREADY_RUNNING = 'A crawl or Extend Knowledge job is already running for this widget'


class CrawlSummary(BaseModel):
    pages: int
    files: int
    resources: int
    errors: int
    selected_pages: int
    selectable_pages: int
    selected_files: int
    selectable_files: int


class CrawlStateResponse(BaseModel):
    config: Optional[ChatWidgetCrawlConfigModel] = None
    current_run: Optional[ChatWidgetCrawlRunModel] = None
    results_run: Optional[ChatWidgetCrawlRunModel] = None
    summary: Optional[CrawlSummary] = None
    knowledge_id: Optional[str] = None
    knowledge_item_count: int = 0


class CrawlSelectionForm(BaseModel):
    model_config = ConfigDict(extra='forbid')

    selected: bool
    item_ids: Optional[list[str]] = Field(default=None, max_length=5000)
    kind: Optional[Literal['page', 'file']] = None

    @model_validator(mode='after')
    def check_target(self):
        if self.item_ids is None and self.kind is None:
            raise ValueError('Provide item_ids or kind')
        return self


async def _get_owned_widget(widget_id: str, user, db: AsyncSession) -> ChatWidgetModel:
    widget = await ChatWidgets.get_widget_by_id_and_user_id(widget_id, user.id, db=db)
    if not widget:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)
    return widget


async def _get_owned_run(widget: ChatWidgetModel, run_id: str, db: AsyncSession) -> ChatWidgetCrawlRunModel:
    run = await ChatWidgetCrawlRuns.get_run_by_id_and_widget_id(run_id, widget.id, db=db)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)
    return run


async def _ensure_latest_completed_run(widget: ChatWidgetModel, run: ChatWidgetCrawlRunModel, db: AsyncSession) -> None:
    latest_completed = await ChatWidgetCrawlRuns.get_latest_completed_run(widget.id, db=db)
    if run.status != 'completed' or not latest_completed or latest_completed.id != run.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Only the latest completed crawl can be changed or added to knowledge',
        )


async def _ensure_url_allowed(url: str) -> None:
    try:
        await asyncio.to_thread(validate_url, url)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='The website URL is invalid or not allowed')


def _is_active(run: ChatWidgetCrawlRunModel) -> bool:
    return run.status in ACTIVE_STATUSES or run.extend_status in ACTIVE_STATUSES


@router.get('/{widget_id}/crawl/state', response_model=CrawlStateResponse)
async def get_crawl_state(
    widget_id: str,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    widget = await _get_owned_widget(widget_id, user, db)
    await ChatWidgetCrawlRuns.expire_stale_runs(widget.id, db=db)

    config = await ChatWidgetCrawlConfigs.get_by_widget_id(widget.id, db=db)
    current_run = await ChatWidgetCrawlRuns.get_latest_run(widget.id, db=db)
    results_run = await ChatWidgetCrawlRuns.get_latest_completed_run(widget.id, db=db)
    summary = CrawlSummary(**await ChatWidgetCrawlItems.get_summary(results_run.id, db=db)) if results_run else None

    return CrawlStateResponse(
        config=config,
        current_run=current_run,
        results_run=results_run,
        summary=summary,
        knowledge_id=widget.knowledge_id,
        knowledge_item_count=await ChatWidgetKnowledgeItems.count_items_by_widget_id(widget.id, db=db),
    )


@router.put('/{widget_id}/crawl/config', response_model=ChatWidgetCrawlConfigModel)
async def save_crawl_config(
    widget_id: str,
    form_data: ChatWidgetCrawlSettings,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    widget = await _get_owned_widget(widget_id, user, db)
    await _ensure_url_allowed(form_data.start_url)
    return await ChatWidgetCrawlConfigs.upsert(widget.id, form_data, db=db)


@router.post('/{widget_id}/crawl/runs', response_model=ChatWidgetCrawlRunModel)
async def start_crawl(
    widget_id: str,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    widget = await _get_owned_widget(widget_id, user, db)
    config = await ChatWidgetCrawlConfigs.get_by_widget_id(widget.id, db=db)
    if not config:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Save the crawl settings first')
    await _ensure_url_allowed(config.settings.start_url)

    async with job_start_lock:
        await ChatWidgetCrawlRuns.expire_stale_runs(widget.id, db=db)
        if await ChatWidgetCrawlRuns.get_active_run(widget.id, db=db):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=JOB_ALREADY_RUNNING)

        run = await ChatWidgetCrawlRuns.create_run(widget.id, user.id, config.settings, db=db)
        run_id = run.id
        start_job(widget.id, run_id, 'crawl', lambda cancel_event: run_crawl(run_id, cancel_event))

    return run


@router.get('/{widget_id}/crawl/runs/{run_id}/items', response_model=list[ChatWidgetCrawlItemResponse])
async def get_crawl_items(
    widget_id: str,
    run_id: str,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    widget = await _get_owned_widget(widget_id, user, db)
    run = await _get_owned_run(widget, run_id, db)
    return await ChatWidgetCrawlItems.get_item_responses_by_run_id(run.id, db=db)


@router.post('/{widget_id}/crawl/runs/{run_id}/selection', response_model=CrawlSummary)
async def set_crawl_selection(
    widget_id: str,
    run_id: str,
    form_data: CrawlSelectionForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    widget = await _get_owned_widget(widget_id, user, db)
    run = await _get_owned_run(widget, run_id, db)
    await _ensure_latest_completed_run(widget, run, db)
    if run.extend_status in ACTIVE_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Wait until Extend Knowledge finishes')

    await ChatWidgetCrawlItems.set_selected(
        run.id, form_data.selected, item_ids=form_data.item_ids, kind=form_data.kind, db=db
    )
    return CrawlSummary(**await ChatWidgetCrawlItems.get_summary(run.id, db=db))


@router.post('/{widget_id}/crawl/runs/{run_id}/cancel', response_model=ChatWidgetCrawlRunModel)
async def cancel_crawl_job(
    widget_id: str,
    run_id: str,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    widget = await _get_owned_widget(widget_id, user, db)
    run = await _get_owned_run(widget, run_id, db)
    if not _is_active(run):
        return run

    await ChatWidgetCrawlRuns.request_cancel(run.id, db=db)
    request_cancel(widget.id)
    return await ChatWidgetCrawlRuns.get_run_by_id(run.id, db=db)


@router.post('/{widget_id}/crawl/runs/{run_id}/extend', response_model=ChatWidgetCrawlRunModel)
async def extend_widget_knowledge(
    request: Request,
    widget_id: str,
    run_id: str,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    widget = await _get_owned_widget(widget_id, user, db)
    run = await _get_owned_run(widget, run_id, db)
    await _ensure_latest_completed_run(widget, run, db)

    config = await ChatWidgetCrawlConfigs.get_by_widget_id(widget.id, db=db)
    if not config or config.settings.model_dump() != run.settings.model_dump():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Crawl settings changed. Re-crawl before extending knowledge.',
        )

    async with job_start_lock:
        await ChatWidgetCrawlRuns.expire_stale_runs(widget.id, db=db)
        if await ChatWidgetCrawlRuns.get_active_run(widget.id, db=db):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=JOB_ALREADY_RUNNING)

        started = await ChatWidgetCrawlRuns.start_extend(run.id, db=db)
        run_id_value = run.id
        start_job(
            widget.id,
            run_id_value,
            'extend',
            lambda cancel_event: run_extend(request, run_id_value, cancel_event),
        )

    return started
```

**Done when:** the module imports without errors.

---

## T10 — Register the router

**File:** `backend/open_webui/main.py`

1. In the big `from open_webui.routers import ( ... )` block, add `widget_crawl,` on its own line **directly before** the existing `widgets,` line (keep alphabetical order):
   ```python
       widget_crawl,
       widgets,
   ```
2. Find this existing line:
   ```python
   app.include_router(widgets.router, prefix='/api/v1/widgets', tags=['widgets'])
   ```
   Add this line **directly after** it:
   ```python
   app.include_router(widget_crawl.router, prefix='/api/v1/widgets', tags=['widgets'])
   ```

**Done when:** the backend starts and `GET /api/v1/widgets/<your-widget-id>/crawl/state` (with a valid user token) returns JSON with `"config": null`.

---

## T11 — Use the knowledge in public widget chat

**File:** `backend/open_webui/routers/widgets.py`

1. Add this constant **directly after** the line `WIDGET_FOLDER_PREFIX = 'Widget: '`:
   ```python
   WIDGET_KNOWLEDGE_INSTRUCTION = (
       'Use the provided website knowledge to answer. Some knowledge entries describe downloadable resources '
       '(link only): you may tell the user the resource exists and share its URL and the page where it was found, '
       'but never claim to know what is inside it.'
   )
   ```
2. In `create_public_widget_chat_message`, replace this block:
   ```python
       messages = []
       if widget.system_prompt:
           messages.append({'role': 'system', 'content': widget.system_prompt})
       messages.append({'role': 'user', 'content': form_data.message})
   ```
   with:
   ```python
       system_prompt = widget.system_prompt or ''
       if widget.knowledge_id:
           system_prompt = f'{system_prompt}\n\n{WIDGET_KNOWLEDGE_INSTRUCTION}'.strip()

       messages = []
       if system_prompt:
           messages.append({'role': 'system', 'content': system_prompt})
       messages.append({'role': 'user', 'content': form_data.message})
   ```
3. In the same function, directly **after** these existing lines:
   ```python
       if widget.mcp_enabled and widget.mcp_tool_ids:
           form_payload['tool_ids'] = list(widget.mcp_tool_ids)
   ```
   add:
   ```python
       if widget.knowledge_id:
           form_payload['files'] = [{'type': 'collection', 'id': widget.knowledge_id}]
   ```

**Done when:** after an Extend Knowledge (T16 done), asking the widget a question answered only on the crawled site gets a correct answer with sources.

---

## T12 — Clean up crawl data when a widget is deleted

**File:** `backend/open_webui/routers/widgets.py`

1. Add these imports to the import section at the top of the file (put them after the `from open_webui.models.chat_widgets import (...)` block):
   ```python
   from open_webui.models.chat_widget_crawl import (
       ChatWidgetCrawlConfigs,
       ChatWidgetCrawlRuns,
       ChatWidgetKnowledgeItems,
   )
   from open_webui.utils.widget_crawl_jobs import request_cancel as request_widget_job_cancel
   from open_webui.utils.widget_knowledge_sync import delete_widget_knowledge
   ```
2. Replace the whole `delete_widget_by_id` function with:
   ```python
   @router.delete('/{widget_id}', response_model=bool)
   async def delete_widget_by_id(
       widget_id: str,
       user=Depends(get_verified_user),
       db: AsyncSession = Depends(get_async_session),
   ):
       widget = await ChatWidgets.get_widget_by_id_and_user_id(widget_id, user.id, db=db)
       if not widget:
           raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)

       request_widget_job_cancel(widget.id)
       if widget.knowledge_id:
           await delete_widget_knowledge(widget.id, widget.knowledge_id)
       await ChatWidgetKnowledgeItems.delete_items_by_widget_id(widget.id, db=db)
       await ChatWidgetCrawlRuns.delete_runs_by_widget_id(widget.id, db=db)
       await ChatWidgetCrawlConfigs.delete_by_widget_id(widget.id, db=db)

       deleted = await ChatWidgets.delete_widget_by_id_and_user_id(widget_id, user.id, db=db)
       if not deleted:
           raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)
       return True
   ```

**Done when:** deleting a widget that had Extend Knowledge removes its "Widget: … (website)" knowledge base from Workspace → Knowledge and leaves no rows in the 4 crawl tables for that widget.

---

## T13 — Frontend API client

**File (new):** `src/lib/apis/widgets/crawl.ts` — copy exactly:

```ts
import { WEBUI_API_BASE_URL } from '$lib/constants';

export type CrawlFileType = 'pdf' | 'docx' | 'xlsx' | 'csv' | 'txt' | 'pptx';

export const SUPPORTED_CRAWL_FILE_TYPES: CrawlFileType[] = ['pdf', 'docx', 'xlsx', 'csv', 'txt', 'pptx'];

export type CrawlSettings = {
	start_url: string;
	max_depth: number;
	max_pages: number;
	same_domain_only: boolean;
	follow_sitemap: boolean;
	respect_robots: boolean;
	discover_files: boolean;
	include_paths: string[];
	exclude_paths: string[];
	allowed_file_types: CrawlFileType[];
	max_file_size_mb: number;
	max_total_size_mb: number;
	request_timeout: number;
	request_delay_ms: number;
	max_concurrency: number;
};

// Must match backend ChatWidgetCrawlSettings defaults exactly.
export const DEFAULT_CRAWL_SETTINGS: CrawlSettings = {
	start_url: '',
	max_depth: 2,
	max_pages: 100,
	same_domain_only: true,
	follow_sitemap: true,
	respect_robots: true,
	discover_files: true,
	include_paths: [],
	exclude_paths: [],
	allowed_file_types: [...SUPPORTED_CRAWL_FILE_TYPES],
	max_file_size_mb: 20,
	max_total_size_mb: 500,
	request_timeout: 20,
	request_delay_ms: 500,
	max_concurrency: 2
};

export type CrawlConfig = {
	id: string;
	widget_id: string;
	settings: CrawlSettings;
	created_at: number;
	updated_at: number;
};

export type CrawlJobStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

export type CrawlRun = {
	id: string;
	widget_id: string;
	user_id: string;
	settings: CrawlSettings;
	status: CrawlJobStatus;
	progress: Record<string, any>;
	error?: string | null;
	cancel_requested: boolean;
	heartbeat_at?: number | null;
	started_at?: number | null;
	finished_at?: number | null;
	extend_status?: CrawlJobStatus | null;
	extend_progress: Record<string, any>;
	extend_error?: string | null;
	extend_started_at?: number | null;
	extend_finished_at?: number | null;
	created_at: number;
};

export type CrawlSummary = {
	pages: number;
	files: number;
	resources: number;
	errors: number;
	selected_pages: number;
	selectable_pages: number;
	selected_files: number;
	selectable_files: number;
};

export type CrawlState = {
	config: CrawlConfig | null;
	current_run: CrawlRun | null;
	results_run: CrawlRun | null;
	summary: CrawlSummary | null;
	knowledge_id: string | null;
	knowledge_item_count: number;
};

export type CrawlItemKind = 'page' | 'file' | 'resource' | 'error';

export type CrawlItem = {
	id: string;
	run_id: string;
	kind: CrawlItemKind;
	url: string;
	title?: string | null;
	name?: string | null;
	file_type?: string | null;
	size?: number | null;
	depth?: number | null;
	found_on?: string | null;
	found_on_title?: string | null;
	link_text?: string | null;
	context?: string | null;
	status: string;
	http_status?: number | null;
	selected: boolean;
	extract_status?: string | null;
	extract_error?: string | null;
};

export type CrawlSelectionForm = {
	selected: boolean;
	item_ids: string[] | null;
	kind: 'page' | 'file' | null;
};

// Builds settings in a fixed key order so two settings objects can be compared with JSON.stringify.
export const canonicalCrawlSettings = (settings: Partial<CrawlSettings>): CrawlSettings => {
	const fileTypes = settings.allowed_file_types ?? DEFAULT_CRAWL_SETTINGS.allowed_file_types;
	return {
		start_url: (settings.start_url ?? '').trim(),
		max_depth: Number(settings.max_depth ?? DEFAULT_CRAWL_SETTINGS.max_depth),
		max_pages: Number(settings.max_pages ?? DEFAULT_CRAWL_SETTINGS.max_pages),
		same_domain_only: settings.same_domain_only ?? DEFAULT_CRAWL_SETTINGS.same_domain_only,
		follow_sitemap: settings.follow_sitemap ?? DEFAULT_CRAWL_SETTINGS.follow_sitemap,
		respect_robots: settings.respect_robots ?? DEFAULT_CRAWL_SETTINGS.respect_robots,
		discover_files: settings.discover_files ?? DEFAULT_CRAWL_SETTINGS.discover_files,
		include_paths: [...(settings.include_paths ?? [])],
		exclude_paths: [...(settings.exclude_paths ?? [])],
		allowed_file_types: SUPPORTED_CRAWL_FILE_TYPES.filter((type) => fileTypes.includes(type)),
		max_file_size_mb: Number(settings.max_file_size_mb ?? DEFAULT_CRAWL_SETTINGS.max_file_size_mb),
		max_total_size_mb: Number(settings.max_total_size_mb ?? DEFAULT_CRAWL_SETTINGS.max_total_size_mb),
		request_timeout: Number(settings.request_timeout ?? DEFAULT_CRAWL_SETTINGS.request_timeout),
		request_delay_ms: Number(settings.request_delay_ms ?? DEFAULT_CRAWL_SETTINGS.request_delay_ms),
		max_concurrency: Number(settings.max_concurrency ?? DEFAULT_CRAWL_SETTINGS.max_concurrency)
	};
};

const parseError = async (res: Response) => {
	try {
		const json = await res.json();
		const detail = json?.detail ?? json;
		if (Array.isArray(detail)) {
			return detail.map((item) => item?.msg ?? JSON.stringify(item)).join(', ');
		}
		return detail;
	} catch {
		return res.statusText;
	}
};

const request = async <T>(token: string, path: string, method = 'GET', body?: unknown): Promise<T> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/widgets/${path}`, {
		method,
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: body === undefined ? undefined : JSON.stringify(body)
	});
	if (!res.ok) throw await parseError(res);
	return res.json();
};

export const getWidgetCrawlState = (token: string, widgetId: string) =>
	request<CrawlState>(token, `${encodeURIComponent(widgetId)}/crawl/state`);

export const saveWidgetCrawlConfig = (token: string, widgetId: string, settings: CrawlSettings) =>
	request<CrawlConfig>(token, `${encodeURIComponent(widgetId)}/crawl/config`, 'PUT', settings);

export const startWidgetCrawl = (token: string, widgetId: string) =>
	request<CrawlRun>(token, `${encodeURIComponent(widgetId)}/crawl/runs`, 'POST');

export const getWidgetCrawlItems = (token: string, widgetId: string, runId: string) =>
	request<CrawlItem[]>(
		token,
		`${encodeURIComponent(widgetId)}/crawl/runs/${encodeURIComponent(runId)}/items`
	);

export const setWidgetCrawlSelection = (
	token: string,
	widgetId: string,
	runId: string,
	form: CrawlSelectionForm
) =>
	request<CrawlSummary>(
		token,
		`${encodeURIComponent(widgetId)}/crawl/runs/${encodeURIComponent(runId)}/selection`,
		'POST',
		form
	);

export const cancelWidgetCrawlRun = (token: string, widgetId: string, runId: string) =>
	request<CrawlRun>(
		token,
		`${encodeURIComponent(widgetId)}/crawl/runs/${encodeURIComponent(runId)}/cancel`,
		'POST'
	);

export const extendWidgetKnowledge = (token: string, widgetId: string, runId: string) =>
	request<CrawlRun>(
		token,
		`${encodeURIComponent(widgetId)}/crawl/runs/${encodeURIComponent(runId)}/extend`,
		'POST'
	);
```

**Done when:** `npm run check` shows no new errors for this file.

---

## T14 — Crawl UI component

**File (new):** `src/lib/components/workspace/WidgetCrawl.svelte` — copy exactly:

```svelte
<script lang="ts">
	import { getContext, onDestroy, onMount } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';
	import { toast } from 'svelte-sonner';

	import type { ChatWidget } from '$lib/apis/widgets';
	import {
		DEFAULT_CRAWL_SETTINGS,
		SUPPORTED_CRAWL_FILE_TYPES,
		canonicalCrawlSettings,
		cancelWidgetCrawlRun,
		extendWidgetKnowledge,
		getWidgetCrawlItems,
		getWidgetCrawlState,
		saveWidgetCrawlConfig,
		setWidgetCrawlSelection,
		startWidgetCrawl,
		type CrawlFileType,
		type CrawlItem,
		type CrawlItemKind,
		type CrawlSettings,
		type CrawlState
	} from '$lib/apis/widgets/crawl';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import Switch from '$lib/components/common/Switch.svelte';

	export let widget: ChatWidget;

	const i18n = getContext<Writable<i18nType>>('i18n');

	const POLL_INTERVAL_MS = 2000;
	const PAGE_SIZE = 100;
	const ACTIVE_STATUSES = ['pending', 'running'];

	const inputClass =
		'w-full rounded-lg border border-gray-200 bg-transparent px-3 py-2 text-sm outline-none focus:border-gray-400 disabled:opacity-60 dark:border-gray-800';
	const labelClass = 'mb-1 text-xs font-medium text-gray-600 dark:text-gray-400';
	const primaryButtonClass =
		'rounded-lg bg-gray-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-white dark:text-gray-900 dark:hover:bg-gray-100';
	const secondaryButtonClass =
		'rounded-lg border border-gray-200 px-3 py-1.5 text-sm font-medium hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-800 dark:hover:bg-gray-850';
	const dangerButtonClass =
		'rounded-lg border border-red-200 px-3 py-1.5 text-sm font-medium text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-red-900 dark:hover:bg-red-950';

	const TABS: { kind: CrawlItemKind; label: string }[] = [
		{ kind: 'page', label: 'Pages' },
		{ kind: 'file', label: 'Files' },
		{ kind: 'resource', label: 'Other resources' },
		{ kind: 'error', label: 'Errors' }
	];

	const STATUS_LABELS: Record<string, string> = {
		ok: 'OK',
		supported: 'Supported',
		too_large: 'Too large',
		not_a_file: 'Not a file (HTML page)',
		robots_disallowed: 'Blocked by robots.txt',
		http_error: 'HTTP error',
		timeout: 'Timeout',
		blocked: 'Blocked or unresolvable address',
		connection_error: 'Connection error',
		too_many_redirects: 'Too many redirects',
		redirect_off_site: 'Redirected to another site'
	};

	const EXTRACT_LABELS: Record<string, string> = {
		embedded: 'Embedded',
		unchanged: 'Embedded (unchanged)',
		no_text: 'No extractable text found',
		failed: 'Extraction failed',
		skipped_limit: 'Skipped (total size limit)'
	};

	const JOB_STATUS_LABELS: Record<string, string> = {
		pending: 'Queued',
		running: 'Running',
		completed: 'Completed',
		failed: 'Failed',
		cancelled: 'Cancelled'
	};

	const PHASE_LABELS: Record<string, string> = {
		starting: 'Starting',
		sitemap: 'Reading sitemap',
		pages: 'Crawling pages',
		files: 'Checking files',
		saving: 'Saving results',
		done: 'Done'
	};

	const LIMIT_LABELS: Record<string, string> = {
		max_pages: 'Maximum pages reached. Some pages were not crawled.',
		max_total_size: 'Maximum total download size reached. Some pages were not crawled.',
		max_linked_items: 'Maximum number of linked files reached. Some files were not recorded.'
	};

	const WARNING_STATUSES = ['too_large', 'not_a_file', 'robots_disallowed'];
	const WARNING_EXTRACT_STATUSES = ['no_text', 'skipped_limit'];

	let loaded = false;
	let crawlState: CrawlState | null = null;
	let items: CrawlItem[] = [];
	let itemsKey = '';
	let settings: CrawlSettings = canonicalCrawlSettings(DEFAULT_CRAWL_SETTINGS);
	let includePathsText = '';
	let excludePathsText = '';
	let saving = false;
	let starting = false;
	let extending = false;
	let cancelling = false;
	let activeTab: CrawlItemKind = 'page';
	let search = '';
	let visibleCount = PAGE_SIZE;
	let pollTimer: ReturnType<typeof setTimeout> | null = null;
	let destroyed = false;

	const parseLines = (value: string) =>
		value
			.split('\n')
			.map((line) => line.trim())
			.filter((line, index, all) => line && all.indexOf(line) === index);

	$: formSettings = canonicalCrawlSettings({
		...settings,
		include_paths: parseLines(includePathsText),
		exclude_paths: parseLines(excludePathsText)
	});
	$: savedSettings = crawlState?.config ? canonicalCrawlSettings(crawlState.config.settings) : null;
	$: formDirty = !savedSettings || JSON.stringify(formSettings) !== JSON.stringify(savedSettings);
	$: currentRun = crawlState?.current_run ?? null;
	$: resultsRun = crawlState?.results_run ?? null;
	$: summary = crawlState?.summary ?? null;
	$: crawlActive = !!currentRun && ACTIVE_STATUSES.includes(currentRun.status);
	$: extendActive = !!resultsRun && ACTIVE_STATUSES.includes(resultsRun.extend_status ?? '');
	$: jobActive = crawlActive || extendActive;
	$: settingsChangedSinceCrawl =
		!!resultsRun &&
		!!savedSettings &&
		JSON.stringify(canonicalCrawlSettings(resultsRun.settings)) !== JSON.stringify(savedSettings);
	$: canExtend =
		!!resultsRun && !jobActive && !formDirty && !settingsChangedSinceCrawl && !extending;
	$: tabCounts = {
		page: items.filter((item) => item.kind === 'page').length,
		file: items.filter((item) => item.kind === 'file').length,
		resource: items.filter((item) => item.kind === 'resource').length,
		error: items.filter((item) => item.kind === 'error').length
	};
	$: tabItems = items.filter((item) => item.kind === activeTab);
	$: searchTerm = search.trim().toLowerCase();
	$: filteredItems = searchTerm
		? tabItems.filter((item) =>
				`${item.title ?? ''} ${item.name ?? ''} ${item.url}`.toLowerCase().includes(searchTerm)
			)
		: tabItems;
	$: visibleItems = filteredItems.slice(0, visibleCount);

	const isSelectable = (item: CrawlItem) =>
		(item.kind === 'page' && item.status === 'ok') ||
		(item.kind === 'file' && item.status === 'supported');

	const humanSize = (bytes: number | null | undefined) => {
		if (bytes === null || bytes === undefined) return '—';
		const units = ['B', 'KB', 'MB', 'GB'];
		let value = bytes;
		let unit = 0;
		while (value >= 1024 && unit < units.length - 1) {
			value /= 1024;
			unit += 1;
		}
		return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
	};

	const statusText = (item: CrawlItem) => {
		let text = $i18n.t(STATUS_LABELS[item.status] ?? item.status);
		if (item.http_status) text = `${text} (${item.http_status})`;
		if (item.extract_status) {
			text = `${text} · ${$i18n.t(EXTRACT_LABELS[item.extract_status] ?? item.extract_status)}`;
		}
		return text;
	};

	const statusClass = (item: CrawlItem) => {
		if (item.kind === 'error' || item.extract_status === 'failed') return 'text-red-600';
		if (
			WARNING_STATUSES.includes(item.status) ||
			WARNING_EXTRACT_STATUSES.includes(item.extract_status ?? '')
		) {
			return 'text-amber-600';
		}
		if (item.extract_status === 'embedded' || item.extract_status === 'unchanged') {
			return 'text-green-600';
		}
		return 'text-gray-600 dark:text-gray-400';
	};

	const formatTime = (seconds: number | null | undefined) =>
		seconds ? new Date(seconds * 1000).toLocaleString() : '—';

	const applySettings = (value: CrawlSettings | null) => {
		const fallbackDomain = (widget.allowed_domains ?? []).find(
			(domain) => domain && !domain.startsWith('*')
		);
		const next = canonicalCrawlSettings(
			value ?? {
				...DEFAULT_CRAWL_SETTINGS,
				start_url: fallbackDomain ? `https://${fallbackDomain}` : ''
			}
		);
		settings = next;
		includePathsText = next.include_paths.join('\n');
		excludePathsText = next.exclude_paths.join('\n');
	};

	const toggleFileType = (type: CrawlFileType) => {
		settings = {
			...settings,
			allowed_file_types: settings.allowed_file_types.includes(type)
				? settings.allowed_file_types.filter((value) => value !== type)
				: [...settings.allowed_file_types, type]
		};
	};

	const setTab = (kind: CrawlItemKind) => {
		activeTab = kind;
		visibleCount = PAGE_SIZE;
	};

	const loadItems = async () => {
		if (!crawlState?.results_run) {
			items = [];
			return;
		}
		const res = await getWidgetCrawlItems(
			localStorage.token,
			widget.id,
			crawlState.results_run.id
		).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		if (res && !destroyed) items = res;
	};

	const schedulePoll = () => {
		if (pollTimer) clearTimeout(pollTimer);
		pollTimer = null;
		if (destroyed) return;
		const run = crawlState?.current_run;
		const results = crawlState?.results_run;
		const active =
			(run && ACTIVE_STATUSES.includes(run.status)) ||
			(results && ACTIVE_STATUSES.includes(results.extend_status ?? ''));
		if (active) pollTimer = setTimeout(loadState, POLL_INTERVAL_MS);
	};

	const loadState = async () => {
		const res = await getWidgetCrawlState(localStorage.token, widget.id).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		if (!res || destroyed) return;

		const firstLoad = !crawlState;
		crawlState = res;
		if (firstLoad) applySettings(res.config?.settings ?? null);

		const key = res.results_run
			? `${res.results_run.id}:${res.results_run.extend_status ?? ''}:${res.results_run.extend_finished_at ?? ''}`
			: '';
		if (key !== itemsKey) {
			itemsKey = key;
			await loadItems();
		}
		schedulePoll();
	};

	const saveSettings = async (): Promise<boolean> => {
		if (!formSettings.start_url) {
			toast.error($i18n.t('Website URL is required'));
			return false;
		}
		saving = true;
		const res = await saveWidgetCrawlConfig(localStorage.token, widget.id, formSettings).catch(
			(error) => {
				toast.error(`${error}`);
				return null;
			}
		);
		saving = false;
		if (!res) return false;
		if (crawlState) crawlState = { ...crawlState, config: res };
		applySettings(res.settings);
		toast.success($i18n.t('Saved'));
		return true;
	};

	const startCrawl = async () => {
		if (jobActive) return;
		if (formDirty && !(await saveSettings())) return;
		starting = true;
		const run = await startWidgetCrawl(localStorage.token, widget.id).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		starting = false;
		if (run) {
			toast.success($i18n.t('Crawl started'));
			await loadState();
		}
	};

	const extendKnowledge = async () => {
		if (!resultsRun || !canExtend) return;
		extending = true;
		const run = await extendWidgetKnowledge(localStorage.token, widget.id, resultsRun.id).catch(
			(error) => {
				toast.error(`${error}`);
				return null;
			}
		);
		extending = false;
		if (run) {
			toast.success($i18n.t('Extend Knowledge started'));
			await loadState();
		}
	};

	const cancelJob = async () => {
		const run = crawlActive ? currentRun : extendActive ? resultsRun : null;
		if (!run) return;
		cancelling = true;
		await cancelWidgetCrawlRun(localStorage.token, widget.id, run.id).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		cancelling = false;
		await loadState();
	};

	const toggleItem = async (item: CrawlItem, selected: boolean) => {
		if (!resultsRun || extendActive || !isSelectable(item)) return;
		const previous = item.selected;
		items = items.map((value) => (value.id === item.id ? { ...value, selected } : value));
		const res = await setWidgetCrawlSelection(localStorage.token, widget.id, resultsRun.id, {
			selected,
			item_ids: [item.id],
			kind: null
		}).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		if (!res) {
			items = items.map((value) =>
				value.id === item.id ? { ...value, selected: previous } : value
			);
			return;
		}
		if (crawlState) crawlState = { ...crawlState, summary: res };
	};

	const selectAllInTab = async (selected: boolean) => {
		if (!resultsRun || extendActive) return;
		if (activeTab !== 'page' && activeTab !== 'file') return;
		const kind = activeTab;
		const res = await setWidgetCrawlSelection(localStorage.token, widget.id, resultsRun.id, {
			selected,
			item_ids: null,
			kind
		}).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		if (!res) return;
		items = items.map((value) =>
			value.kind === kind && isSelectable(value) ? { ...value, selected } : value
		);
		if (crawlState) crawlState = { ...crawlState, summary: res };
	};

	onMount(async () => {
		await loadState();
		loaded = true;
	});

	onDestroy(() => {
		destroyed = true;
		if (pollTimer) clearTimeout(pollTimer);
	});
</script>

<section class="mt-3 rounded-lg border border-gray-100 dark:border-gray-850">
	<div
		class="flex flex-wrap items-center justify-between gap-2 border-b border-gray-100 px-4 py-3 dark:border-gray-850"
	>
		<div>
			<div class="text-sm font-medium">{$i18n.t('Website knowledge')}</div>
			<div class="text-xs text-gray-500">
				{$i18n.t('Crawl a website, review what was found, then add it to the widget knowledge.')}
			</div>
		</div>
		{#if crawlState?.knowledge_id}
			<div class="text-xs text-gray-500">
				{crawlState.knowledge_item_count}
				{$i18n.t('items in widget knowledge')}
			</div>
		{/if}
	</div>

	{#if !loaded}
		<div class="flex h-32 items-center justify-center">
			<Spinner />
		</div>
	{:else}
		<div class="space-y-4 p-4">
			<div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
				<div class="space-y-3">
					<label class="block">
						<div class={labelClass}>{$i18n.t('Website URL')}</div>
						<input
							class={inputClass}
							bind:value={settings.start_url}
							placeholder="https://example.com"
							disabled={jobActive}
						/>
					</label>

					<div class="grid grid-cols-2 gap-3">
						<label class="block">
							<div class={labelClass}>{$i18n.t('Crawl depth')}</div>
							<input
								type="number"
								min="0"
								max="5"
								class={inputClass}
								bind:value={settings.max_depth}
								disabled={jobActive}
							/>
						</label>
						<label class="block">
							<div class={labelClass}>{$i18n.t('Maximum pages')}</div>
							<input
								type="number"
								min="1"
								max="1000"
								class={inputClass}
								bind:value={settings.max_pages}
								disabled={jobActive}
							/>
						</label>
					</div>

					<label class="block">
						<div class={labelClass}>{$i18n.t('Include paths')}</div>
						<textarea
							class="{inputClass} min-h-20"
							bind:value={includePathsText}
							placeholder={'/docs\n/blog'}
							disabled={jobActive}
						></textarea>
						<div class="mt-1 text-xs text-gray-500">
							{$i18n.t(
								'One path per line. Only pages whose path starts with one of these are crawled. Leave empty to crawl all paths.'
							)}
						</div>
					</label>

					<label class="block">
						<div class={labelClass}>{$i18n.t('Exclude paths')}</div>
						<textarea
							class="{inputClass} min-h-20"
							bind:value={excludePathsText}
							placeholder={'/admin\n/login'}
							disabled={jobActive}
						></textarea>
						<div class="mt-1 text-xs text-gray-500">
							{$i18n.t('One path per line. Pages whose path starts with one of these are skipped.')}
						</div>
					</label>
				</div>

				<div class="space-y-3">
					<div
						class="flex items-center justify-between rounded-lg border border-gray-100 px-3 py-2 dark:border-gray-850"
					>
						<div>
							<div class="text-sm font-medium">{$i18n.t('Same domain only')}</div>
							<div class="text-xs text-gray-500">
								{$i18n.t('Only crawl pages on the website domain')}
							</div>
						</div>
						<Switch bind:state={settings.same_domain_only} ariaLabel={$i18n.t('Same domain only')} />
					</div>

					<div
						class="flex items-center justify-between rounded-lg border border-gray-100 px-3 py-2 dark:border-gray-850"
					>
						<div>
							<div class="text-sm font-medium">{$i18n.t('Follow sitemap')}</div>
							<div class="text-xs text-gray-500">
								{$i18n.t('Also crawl pages listed in sitemap.xml')}
							</div>
						</div>
						<Switch bind:state={settings.follow_sitemap} ariaLabel={$i18n.t('Follow sitemap')} />
					</div>

					<div
						class="flex items-center justify-between rounded-lg border border-gray-100 px-3 py-2 dark:border-gray-850"
					>
						<div>
							<div class="text-sm font-medium">{$i18n.t('Respect robots.txt')}</div>
							<div class="text-xs text-gray-500">
								{$i18n.t('Skip URLs the website does not allow crawlers to visit')}
							</div>
						</div>
						<Switch bind:state={settings.respect_robots} ariaLabel={$i18n.t('Respect robots.txt')} />
					</div>

					<div class="rounded-lg border border-gray-100 px-3 py-2 dark:border-gray-850">
						<div class="flex items-center justify-between">
							<div>
								<div class="text-sm font-medium">{$i18n.t('Discover linked files')}</div>
								<div class="text-xs text-gray-500">
									{$i18n.t('Record files and other resources linked from pages')}
								</div>
							</div>
							<Switch
								bind:state={settings.discover_files}
								ariaLabel={$i18n.t('Discover linked files')}
							/>
						</div>
						{#if settings.discover_files}
							<div class="mt-2 flex flex-wrap gap-3">
								{#each SUPPORTED_CRAWL_FILE_TYPES as type (type)}
									<label class="flex items-center gap-1.5 text-xs">
										<input
											type="checkbox"
											checked={settings.allowed_file_types.includes(type)}
											disabled={jobActive}
											on:change={() => toggleFileType(type)}
										/>
										{type.toUpperCase()}
									</label>
								{/each}
							</div>
						{/if}
					</div>

					<div class="grid grid-cols-2 gap-3">
						<label class="block">
							<div class={labelClass}>{$i18n.t('Maximum file size (MB)')}</div>
							<input
								type="number"
								min="1"
								max="100"
								class={inputClass}
								bind:value={settings.max_file_size_mb}
								disabled={jobActive}
							/>
						</label>
						<label class="block">
							<div class={labelClass}>{$i18n.t('Maximum total download (MB)')}</div>
							<input
								type="number"
								min="10"
								max="5000"
								class={inputClass}
								bind:value={settings.max_total_size_mb}
								disabled={jobActive}
							/>
						</label>
						<label class="block">
							<div class={labelClass}>{$i18n.t('Request timeout (seconds)')}</div>
							<input
								type="number"
								min="5"
								max="120"
								class={inputClass}
								bind:value={settings.request_timeout}
								disabled={jobActive}
							/>
						</label>
						<label class="block">
							<div class={labelClass}>{$i18n.t('Delay between requests (ms)')}</div>
							<input
								type="number"
								min="0"
								max="10000"
								class={inputClass}
								bind:value={settings.request_delay_ms}
								disabled={jobActive}
							/>
						</label>
						<label class="block">
							<div class={labelClass}>{$i18n.t('Parallel requests')}</div>
							<input
								type="number"
								min="1"
								max="5"
								class={inputClass}
								bind:value={settings.max_concurrency}
								disabled={jobActive}
							/>
						</label>
					</div>
				</div>
			</div>

			<div
				class="space-y-1 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200"
			>
				<div>
					<span class="font-semibold">{$i18n.t('PDF support:')}</span>
					{$i18n.t(
						'Only extractable text inside PDF files can be added to knowledge. Text inside scanned pages or images is not processed.'
					)}
				</div>
				<div>
					<span class="font-semibold">{$i18n.t('Note:')}</span>
					{$i18n.t('Pages that load their content with JavaScript may appear empty or incomplete.')}
				</div>
			</div>

			<div class="flex flex-wrap items-center gap-2">
				<button
					class={secondaryButtonClass}
					disabled={saving || jobActive || !formDirty}
					on:click={saveSettings}
				>
					{saving ? $i18n.t('Saving...') : $i18n.t('Save settings')}
				</button>
				<button
					class={primaryButtonClass}
					disabled={starting || saving || jobActive}
					on:click={startCrawl}
				>
					{resultsRun ? $i18n.t('Re-crawl') : $i18n.t('Start crawl')}
				</button>
				{#if jobActive}
					<button class={dangerButtonClass} disabled={cancelling} on:click={cancelJob}>
						{$i18n.t('Cancel')}
					</button>
				{/if}
				{#if formDirty && savedSettings}
					<span class="text-xs text-amber-600">{$i18n.t('Unsaved settings')}</span>
				{/if}
			</div>

			{#if currentRun && currentRun.id !== resultsRun?.id}
				<div class="rounded-lg border border-gray-100 px-3 py-2 text-sm dark:border-gray-850">
					<div class="flex items-center gap-2">
						{#if crawlActive}
							<Spinner className="size-4" />
						{/if}
						<span class="font-medium">
							{$i18n.t('Crawl')}: {$i18n.t(JOB_STATUS_LABELS[currentRun.status] ?? currentRun.status)}
						</span>
						{#if crawlActive && currentRun.progress?.phase}
							<span class="text-gray-500">
								· {$i18n.t(PHASE_LABELS[currentRun.progress.phase] ?? currentRun.progress.phase)}
							</span>
						{/if}
					</div>
					{#if crawlActive}
						<div class="mt-1 text-xs text-gray-500">
							{$i18n.t('Pages')}: {currentRun.progress?.pages ?? 0} · {$i18n.t('Files')}:
							{currentRun.progress?.files ?? 0} · {$i18n.t('Other resources')}:
							{currentRun.progress?.resources ?? 0} · {$i18n.t('Errors')}:
							{currentRun.progress?.errors ?? 0} · {$i18n.t('Downloaded')}:
							{humanSize(currentRun.progress?.bytes_downloaded ?? 0)}
						</div>
					{/if}
					{#if currentRun.status === 'failed' && currentRun.error}
						<div class="mt-1 text-xs text-red-600">{currentRun.error}</div>
					{/if}
					{#if currentRun.status === 'cancelled'}
						<div class="mt-1 text-xs text-gray-500">
							{$i18n.t('The crawl was cancelled. Previous results are kept.')}
						</div>
					{/if}
				</div>
			{/if}

			{#if resultsRun && summary}
				<div class="rounded-lg border border-gray-100 dark:border-gray-850">
					<div
						class="flex flex-wrap items-start justify-between gap-3 border-b border-gray-100 px-3 py-3 dark:border-gray-850"
					>
						<div class="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
							<div>{$i18n.t('Pages')}: <span class="font-medium">{summary.pages}</span></div>
							<div>
								{$i18n.t('Supported files')}: <span class="font-medium">{summary.files}</span>
							</div>
							<div>
								{$i18n.t('Other resources')}: <span class="font-medium">{summary.resources}</span>
							</div>
							<div>{$i18n.t('Errors')}: <span class="font-medium">{summary.errors}</span></div>
							<div>
								{$i18n.t('Selected pages')}:
								<span class="font-medium">{summary.selected_pages} / {summary.selectable_pages}</span>
							</div>
							<div>
								{$i18n.t('Selected files')}:
								<span class="font-medium">{summary.selected_files} / {summary.selectable_files}</span>
							</div>
						</div>
						<div class="flex gap-2">
							<button
								class={secondaryButtonClass}
								disabled={starting || saving || jobActive}
								on:click={startCrawl}
							>
								{$i18n.t('Re-crawl')}
							</button>
							<button class={primaryButtonClass} disabled={!canExtend} on:click={extendKnowledge}>
								{$i18n.t('Extend Knowledge')}
							</button>
						</div>
					</div>

					<div class="space-y-1 px-3 py-2 text-xs">
						<div class="text-gray-500">
							{$i18n.t('Crawled')}: {formatTime(resultsRun.finished_at)}
						</div>
						{#if resultsRun.progress?.limit_reached}
							<div class="text-amber-600">
								{$i18n.t(
									LIMIT_LABELS[resultsRun.progress.limit_reached] ?? resultsRun.progress.limit_reached
								)}
							</div>
						{/if}
						{#if settingsChangedSinceCrawl}
							<div class="text-amber-600">
								{$i18n.t('Crawl settings changed since this crawl. Re-crawl before extending knowledge.')}
							</div>
						{:else if formDirty}
							<div class="text-amber-600">
								{$i18n.t('Save or revert your settings changes before extending knowledge.')}
							</div>
						{/if}
						{#if resultsRun.extend_status}
							<div
								class={resultsRun.extend_status === 'failed' ? 'text-red-600' : 'text-gray-600 dark:text-gray-400'}
							>
								<span class="font-medium">
									{$i18n.t('Extend Knowledge')}: {$i18n.t(
										JOB_STATUS_LABELS[resultsRun.extend_status] ?? resultsRun.extend_status
									)}
								</span>
								{#if extendActive}
									· {resultsRun.extend_progress?.done ?? 0} / {resultsRun.extend_progress?.total ?? 0}
								{/if}
								{#if !extendActive && resultsRun.extend_status !== 'failed'}
									· {$i18n.t('Embedded')}: {resultsRun.extend_progress?.embedded ?? 0} · {$i18n.t(
										'Unchanged'
									)}: {resultsRun.extend_progress?.unchanged ?? 0} · {$i18n.t('Removed')}:
									{resultsRun.extend_progress?.removed ?? 0} · {$i18n.t('No text')}:
									{resultsRun.extend_progress?.no_text ?? 0} · {$i18n.t('Failed')}:
									{resultsRun.extend_progress?.failed ?? 0} · {$i18n.t('Skipped')}:
									{resultsRun.extend_progress?.skipped_limit ?? 0}
								{/if}
								{#if resultsRun.extend_status === 'failed' && resultsRun.extend_error}
									· {resultsRun.extend_error}
								{/if}
							</div>
						{/if}
					</div>

					<div
						class="flex flex-wrap items-center gap-2 border-y border-gray-100 px-3 py-2 dark:border-gray-850"
					>
						{#each TABS as tab (tab.kind)}
							<button
								class="rounded-lg px-2.5 py-1 text-sm {activeTab === tab.kind
									? 'bg-gray-100 font-medium dark:bg-gray-850'
									: 'text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-900'}"
								on:click={() => setTab(tab.kind)}
							>
								{$i18n.t(tab.label)} ({tabCounts[tab.kind]})
							</button>
						{/each}
						<div class="flex-1"></div>
						{#if activeTab === 'page' || activeTab === 'file'}
							<button
								class="rounded-lg px-2 py-1 text-xs hover:bg-gray-100 disabled:opacity-50 dark:hover:bg-gray-850"
								disabled={extendActive}
								on:click={() => selectAllInTab(true)}
							>
								{$i18n.t('Select all')}
							</button>
							<button
								class="rounded-lg px-2 py-1 text-xs hover:bg-gray-100 disabled:opacity-50 dark:hover:bg-gray-850"
								disabled={extendActive}
								on:click={() => selectAllInTab(false)}
							>
								{$i18n.t('Select none')}
							</button>
						{/if}
						<input
							class="w-48 rounded-lg border border-gray-200 bg-transparent px-2 py-1 text-xs outline-none focus:border-gray-400 dark:border-gray-800"
							placeholder={$i18n.t('Search')}
							bind:value={search}
							on:input={() => (visibleCount = PAGE_SIZE)}
						/>
					</div>

					{#if activeTab === 'file'}
						<div
							class="border-b border-gray-100 px-3 py-2 text-xs text-amber-700 dark:border-gray-850 dark:text-amber-300"
						>
							<span class="font-semibold">{$i18n.t('PDF support:')}</span>
							{$i18n.t(
								'Only extractable text inside PDF files can be added to knowledge. Text inside scanned pages or images is not processed.'
							)}
						</div>
					{/if}

					<div class="overflow-x-auto">
						{#if filteredItems.length === 0}
							<div class="px-3 py-8 text-center text-sm text-gray-500">
								{$i18n.t('Nothing found')}
							</div>
						{:else if activeTab === 'page'}
							<table class="w-full text-left text-xs">
								<thead class="text-gray-500">
									<tr class="border-b border-gray-100 dark:border-gray-850">
										<th class="w-12 px-3 py-2">{$i18n.t('Embed')}</th>
										<th class="px-3 py-2">{$i18n.t('Page Title')}</th>
										<th class="px-3 py-2">{$i18n.t('URL')}</th>
										<th class="w-16 px-3 py-2">{$i18n.t('Depth')}</th>
										<th class="px-3 py-2">{$i18n.t('Status')}</th>
									</tr>
								</thead>
								<tbody>
									{#each visibleItems as item (item.id)}
										<tr class="border-b border-gray-50 dark:border-gray-900">
											<td class="px-3 py-2">
												<input
													type="checkbox"
													checked={item.selected}
													disabled={!isSelectable(item) || extendActive}
													on:change={(event) => toggleItem(item, event.currentTarget.checked)}
												/>
											</td>
											<td class="max-w-64 truncate px-3 py-2" title={item.title ?? ''}>
												{item.title ?? '—'}
											</td>
											<td class="max-w-80 truncate px-3 py-2">
												<a
													class="hover:underline"
													href={item.url}
													target="_blank"
													rel="noopener noreferrer"
													title={item.url}>{item.url}</a
												>
											</td>
											<td class="px-3 py-2">{item.depth ?? '—'}</td>
											<td class="px-3 py-2 {statusClass(item)}" title={item.extract_error ?? ''}>
												{statusText(item)}
											</td>
										</tr>
									{/each}
								</tbody>
							</table>
						{:else if activeTab === 'file'}
							<table class="w-full text-left text-xs">
								<thead class="text-gray-500">
									<tr class="border-b border-gray-100 dark:border-gray-850">
										<th class="w-12 px-3 py-2">{$i18n.t('Embed')}</th>
										<th class="px-3 py-2">{$i18n.t('Name')}</th>
										<th class="w-16 px-3 py-2">{$i18n.t('Type')}</th>
										<th class="w-20 px-3 py-2">{$i18n.t('Size')}</th>
										<th class="px-3 py-2">{$i18n.t('URL')}</th>
										<th class="px-3 py-2">{$i18n.t('Found On')}</th>
										<th class="px-3 py-2">{$i18n.t('Status')}</th>
									</tr>
								</thead>
								<tbody>
									{#each visibleItems as item (item.id)}
										<tr class="border-b border-gray-50 dark:border-gray-900">
											<td class="px-3 py-2">
												<input
													type="checkbox"
													checked={item.selected}
													disabled={!isSelectable(item) || extendActive}
													on:change={(event) => toggleItem(item, event.currentTarget.checked)}
												/>
											</td>
											<td class="max-w-48 truncate px-3 py-2" title={item.name ?? ''}>
												{item.name ?? '—'}
											</td>
											<td class="px-3 py-2">{(item.file_type ?? '').toUpperCase() || '—'}</td>
											<td class="px-3 py-2">{humanSize(item.size)}</td>
											<td class="max-w-64 truncate px-3 py-2">
												<a
													class="hover:underline"
													href={item.url}
													target="_blank"
													rel="noopener noreferrer"
													title={item.url}>{item.url}</a
												>
											</td>
											<td class="max-w-48 truncate px-3 py-2">
												{#if item.found_on}
													<a
														class="hover:underline"
														href={item.found_on}
														target="_blank"
														rel="noopener noreferrer"
														title={item.found_on}>{item.found_on_title || item.found_on}</a
													>
												{:else}
													—
												{/if}
											</td>
											<td class="px-3 py-2 {statusClass(item)}" title={item.extract_error ?? ''}>
												{statusText(item)}
											</td>
										</tr>
									{/each}
								</tbody>
							</table>
						{:else if activeTab === 'resource'}
							<table class="w-full text-left text-xs">
								<thead class="text-gray-500">
									<tr class="border-b border-gray-100 dark:border-gray-850">
										<th class="px-3 py-2">{$i18n.t('Name')}</th>
										<th class="w-20 px-3 py-2">{$i18n.t('Type')}</th>
										<th class="px-3 py-2">{$i18n.t('URL')}</th>
										<th class="px-3 py-2">{$i18n.t('Found On')}</th>
										<th class="w-20 px-3 py-2">{$i18n.t('Size')}</th>
										<th class="px-3 py-2">{$i18n.t('Link Text / Context')}</th>
									</tr>
								</thead>
								<tbody>
									{#each visibleItems as item (item.id)}
										<tr class="border-b border-gray-50 align-top dark:border-gray-900">
											<td class="max-w-48 truncate px-3 py-2" title={item.name ?? ''}>
												{item.name ?? '—'}
											</td>
											<td class="px-3 py-2">{item.file_type ?? '—'}</td>
											<td class="max-w-64 truncate px-3 py-2">
												<a
													class="hover:underline"
													href={item.url}
													target="_blank"
													rel="noopener noreferrer"
													title={item.url}>{item.url}</a
												>
											</td>
											<td class="max-w-48 truncate px-3 py-2">
												{#if item.found_on}
													<a
														class="hover:underline"
														href={item.found_on}
														target="_blank"
														rel="noopener noreferrer"
														title={item.found_on}>{item.found_on_title || item.found_on}</a
													>
												{:else}
													—
												{/if}
											</td>
											<td class="px-3 py-2">{humanSize(item.size)}</td>
											<td class="max-w-80 px-3 py-2">
												<div class="truncate" title={item.link_text ?? ''}>{item.link_text ?? '—'}</div>
												{#if item.context}
													<div class="line-clamp-2 text-gray-500" title={item.context}>
														{item.context}
													</div>
												{/if}
											</td>
										</tr>
									{/each}
								</tbody>
							</table>
						{:else}
							<table class="w-full text-left text-xs">
								<thead class="text-gray-500">
									<tr class="border-b border-gray-100 dark:border-gray-850">
										<th class="px-3 py-2">{$i18n.t('URL')}</th>
										<th class="px-3 py-2">{$i18n.t('Found On')}</th>
										<th class="px-3 py-2">{$i18n.t('Status')}</th>
										<th class="w-16 px-3 py-2">{$i18n.t('Depth')}</th>
									</tr>
								</thead>
								<tbody>
									{#each visibleItems as item (item.id)}
										<tr class="border-b border-gray-50 dark:border-gray-900">
											<td class="max-w-80 truncate px-3 py-2">
												<a
													class="hover:underline"
													href={item.url}
													target="_blank"
													rel="noopener noreferrer"
													title={item.url}>{item.url}</a
												>
											</td>
											<td class="max-w-48 truncate px-3 py-2">
												{#if item.found_on}
													<a
														class="hover:underline"
														href={item.found_on}
														target="_blank"
														rel="noopener noreferrer"
														title={item.found_on}>{item.found_on_title || item.found_on}</a
													>
												{:else}
													—
												{/if}
											</td>
											<td class="px-3 py-2 {statusClass(item)}">{statusText(item)}</td>
											<td class="px-3 py-2">{item.depth ?? '—'}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						{/if}
					</div>

					{#if filteredItems.length > visibleCount}
						<div class="flex justify-center px-3 py-2">
							<button
								class={secondaryButtonClass}
								on:click={() => (visibleCount = visibleCount + PAGE_SIZE)}
							>
								{$i18n.t('Show more')} ({filteredItems.length - visibleCount})
							</button>
						</div>
					{/if}
				</div>
			{/if}
		</div>
	{/if}
</section>
```

**Done when:** `npm run check` shows no new errors for this file.

---

## T15 — Add `knowledge_id` to the frontend widget type

**File:** `src/lib/apis/widgets/index.ts`

In `export type ChatWidget = { ... }`, add this line **directly after** `folder_id?: string | null;`:
```ts
	knowledge_id?: string | null;
```
Do **not** add it to `ChatWidgetForm`.

---

## T16 — Show the crawl UI on the widget page

**File:** `src/lib/components/workspace/ChatWidgets.svelte`

1. Add this import **directly after** the line `import ChatWidgetPreview from '$lib/components/workspace/ChatWidgetPreview.svelte';`:
   ```ts
   	import WidgetCrawl from '$lib/components/workspace/WidgetCrawl.svelte';
   ```
2. Find the Conversations section, which starts with:
   ```svelte
   		{#if selectedWidget}
   			<section class="mt-3 rounded-lg border border-gray-100 dark:border-gray-850">
   				<div
   					class="flex flex-wrap items-center justify-between gap-2 border-b border-gray-100 px-4 py-3 dark:border-gray-850"
   				>
   					<div>
   						<div class="text-sm font-medium">{$i18n.t('Conversations')}</div>
   ```
   Insert this block **directly before** that `{#if selectedWidget}` line (same indentation):
   ```svelte
   		{#if selectedWidget}
   			{#key selectedWidget.id}
   				<WidgetCrawl widget={selectedWidget} />
   			{/key}
   		{/if}

   ```
3. Do not change anything else in this file.

**Done when:** opening an existing widget in Workspace → Widgets shows the "Website knowledge" section between the editor and Conversations. A new, unsaved widget does not show it.

---

## 3. Manual QA checklist (do all; report results)

Use a small public test site (e.g. your own docs site) with: a few pages, at least one PDF, one DOCX, one ZIP and one image link.

### Settings & validation
- [ ] Save with empty URL → toast "Website URL is required".
- [ ] Save `ftp://example.com` → error toast from the backend.
- [ ] Save `http://127.0.0.1:8080` or `http://localhost` → "The website URL is invalid or not allowed".
- [ ] Include path without leading `/` → error toast "Path must start with "/"".
- [ ] Save valid settings → toast "Saved", the "Unsaved settings" label disappears, and the URL is shown normalized.

### Crawl
- [ ] Start crawl → progress block shows phase and counters, updating every ~2 s.
- [ ] Clicking Start crawl again while running → button disabled. Calling the API directly → HTTP 409.
- [ ] After completion: summary shows counts; tabs show Pages / Files / Other resources / Errors with counts.
- [ ] Pages have titles, depth, status OK, and all are **checked**.
- [ ] PDF/DOCX appear in Files with name, type, size, Found On, status "Supported", **checked**.
- [ ] ZIP and image appear in Other resources with no checkbox, with link text / context.
- [ ] A broken link (404) appears in Errors with "HTTP error (404)".
- [ ] `max_pages = 3` → only 3 page fetches; amber "Maximum pages reached" note.
- [ ] Exclude path `/blog` → no `/blog...` pages.
- [ ] Turn off "Discover linked files" → Files and Other resources are empty after a re-crawl.
- [ ] Cancel during a crawl → status "Cancelled", previous results still shown.
- [ ] Restart the backend during a crawl → within ~2 minutes the state shows the crawl as Failed with "The job stopped unexpectedly…".

### Selection
- [ ] Uncheck 2 pages → "Selected pages" decreases by 2 right away. Reload the page → still unchecked.
- [ ] Select none / Select all work per tab.
- [ ] Re-crawl with the same settings → the 2 pages are **still unchecked**; new pages are checked.
- [ ] Change max depth (unsaved) → Extend Knowledge disabled with "Save or revert…".
- [ ] Save the changed settings → Extend Knowledge disabled with "Crawl settings changed since this crawl…".

### Extend Knowledge
- [ ] Click Extend Knowledge → progress `done / total`; when done, counts are shown; per-item status shows "Embedded".
- [ ] Workspace → Knowledge contains "Widget: <name> (website)" with the files.
- [ ] Run Extend Knowledge again with no changes → everything "Embedded (unchanged)", `Embedded: 0`.
- [ ] Uncheck a page → Extend → `Removed: 1`; the file is gone from the knowledge base.
- [ ] A scanned (image-only) PDF → status "No extractable text found"; it is not in the knowledge base.
- [ ] Ask the public widget about content that only exists on the crawled site → correct answer.
- [ ] Ask the widget about the ZIP → it gives the URL and page, and does **not** invent contents.
- [ ] Delete the widget → its knowledge base disappears from Workspace → Knowledge.

### Regression
- [ ] Widget create/edit/save, theme preview, MCP tools, token rotate and conversations still work.
- [ ] A widget without crawl/knowledge still chats normally.

---

## 4. Definition of done
- All tasks T1–T16 implemented exactly as written.
- `ruff format` run on changed Python files; `npx prettier --write` run on changed TS/Svelte files.
- `npm run check` has no new errors in the new or changed files.
- Backend starts cleanly and the migration applies.
- Every QA checklist item has been checked and the results reported (with screenshots for the Crawl, Selection and Extend sections).
