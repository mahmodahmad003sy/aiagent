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
