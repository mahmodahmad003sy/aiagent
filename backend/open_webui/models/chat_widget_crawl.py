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
