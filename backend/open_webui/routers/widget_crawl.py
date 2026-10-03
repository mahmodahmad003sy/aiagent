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
