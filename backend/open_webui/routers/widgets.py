from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.internal.db import get_async_session
from open_webui.models.chat_widgets import (
    ChatWidgetForm,
    ChatWidgetModel,
    ChatWidgets,
    ChatWidgetUpdateForm,
)
from open_webui.utils.auth import get_verified_user
from open_webui.utils.models import get_all_models, get_filtered_models
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


async def _ensure_model_access(
    request: Request,
    model_id: str,
    user,
    db: AsyncSession,
) -> None:
    if not model_id or len(model_id) > 256:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.MODEL_ID_TOO_LONG,
        )

    models = await get_filtered_models(await get_all_models(request, user=user), user, db=db)
    if not any(model.get('id') == model_id for model in models):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )


@router.post('', response_model=ChatWidgetModel)
async def create_widget(
    request: Request,
    form_data: ChatWidgetForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    await _ensure_model_access(request, form_data.model_id, user, db)
    return await ChatWidgets.insert_new_widget(user.id, form_data, db=db)


@router.get('', response_model=list[ChatWidgetModel])
async def get_widgets(
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    return await ChatWidgets.get_widgets_by_user_id(user.id, db=db)


@router.get('/{widget_id}', response_model=ChatWidgetModel)
async def get_widget_by_id(
    widget_id: str,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    widget = await ChatWidgets.get_widget_by_id_and_user_id(widget_id, user.id, db=db)
    if not widget:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)
    return widget


@router.put('/{widget_id}', response_model=ChatWidgetModel)
async def update_widget_by_id(
    request: Request,
    widget_id: str,
    form_data: ChatWidgetUpdateForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    if form_data.model_id is not None:
        await _ensure_model_access(request, form_data.model_id, user, db)

    widget = await ChatWidgets.update_widget_by_id_and_user_id(widget_id, user.id, form_data, db=db)
    if not widget:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)
    return widget


@router.delete('/{widget_id}', response_model=bool)
async def delete_widget_by_id(
    widget_id: str,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    deleted = await ChatWidgets.delete_widget_by_id_and_user_id(widget_id, user.id, db=db)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)
    return True


@router.post('/{widget_id}/rotate-token', response_model=ChatWidgetModel)
async def rotate_widget_token(
    widget_id: str,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    widget = await ChatWidgets.rotate_token_by_id_and_user_id(widget_id, user.id, db=db)
    if not widget:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)
    return widget
