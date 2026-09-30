from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.internal.db import get_async_session
from open_webui.models.chat_widgets import (
    ChatWidgetMessageForm,
    ChatWidgetMessages,
    ChatWidgetForm,
    ChatWidgetModel,
    ChatWidgetSessionForm,
    ChatWidgetSessions,
    ChatWidgets,
    ChatWidgetUpdateForm,
)
from open_webui.models.users import Users
from open_webui.utils.auth import get_verified_user
from open_webui.utils.models import get_all_models, get_filtered_models
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


class PublicWidgetConfigResponse(BaseModel):
    id: str
    name: str
    welcome_message: Optional[str] = None


class PublicWidgetChatForm(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    widget_id: Optional[str] = None
    session_id: Optional[str] = None
    visitor_id: Optional[str] = None
    model_config = ConfigDict(extra='forbid')

    @field_validator('message')
    @classmethod
    def normalize_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError('Message cannot be empty')
        return value


class PublicWidgetChatResponse(BaseModel):
    widget_id: str
    session_id: str
    message_id: str
    accepted: bool = True


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


def _get_widget_token(request: Request, token: Optional[str] = None) -> Optional[str]:
    if token:
        return token.strip()

    header_token = request.headers.get('x-widget-token')
    if header_token:
        return header_token.strip()

    authorization = request.headers.get('authorization')
    if authorization:
        scheme, _, credentials = authorization.partition(' ')
        if scheme.lower() == 'bearer' and credentials:
            return credentials.strip()

    return None


def _domain_from_value(value: str | None) -> Optional[str]:
    if not value:
        return None

    candidate = value.strip().lower()
    if not candidate:
        return None

    parsed = urlparse(candidate if '://' in candidate else f'//{candidate}', scheme='https')
    host = parsed.hostname or candidate.split('/', 1)[0].split(':', 1)[0]
    return host.strip('.') if host else None


def _request_domain(request: Request) -> Optional[str]:
    return _domain_from_value(request.headers.get('origin')) or _domain_from_value(request.headers.get('referer'))


def _domain_matches(domain: str, allowed_domain: str) -> bool:
    allowed = _domain_from_value(allowed_domain)
    if not allowed:
        return False
    if allowed == '*':
        return True
    if allowed.startswith('*.'):
        suffix = allowed[2:]
        return domain == suffix or domain.endswith(f'.{suffix}')
    return domain == allowed


def _ensure_domain_allowed(request: Request, widget: ChatWidgetModel) -> None:
    allowed_domains = widget.allowed_domains or []
    if not allowed_domains:
        return

    domain = _request_domain(request)
    if not domain or not any(_domain_matches(domain, allowed_domain) for allowed_domain in allowed_domains):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )


async def _get_public_widget(
    request: Request,
    db: AsyncSession,
    token: Optional[str] = None,
    widget_id: Optional[str] = None,
) -> tuple[ChatWidgetModel, object]:
    widget_token = _get_widget_token(request, token)
    if not widget_token or not widget_token.startswith('wgt_'):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=ERROR_MESSAGES.INVALID_TOKEN)

    widget = await ChatWidgets.get_widget_by_token(widget_token, db=db)
    if not widget or (widget_id and widget.id != widget_id):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=ERROR_MESSAGES.INVALID_TOKEN)

    if not widget.enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ERROR_MESSAGES.ACCESS_PROHIBITED)

    _ensure_domain_allowed(request, widget)

    owner = await Users.get_user_by_id(widget.user_id, db=db)
    if not owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ERROR_MESSAGES.ACCESS_PROHIBITED)

    await _ensure_model_access(request, widget.model_id, owner, db)
    return widget, owner


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


@router.get('/public/config', response_model=PublicWidgetConfigResponse)
async def get_public_widget_config(
    request: Request,
    token: Optional[str] = None,
    widget_id: Optional[str] = None,
    db: AsyncSession = Depends(get_async_session),
):
    widget, _ = await _get_public_widget(request, db, token=token, widget_id=widget_id)
    return PublicWidgetConfigResponse(
        id=widget.id,
        name=widget.name,
        welcome_message=widget.welcome_message,
    )


@router.post('/public/chat', response_model=PublicWidgetChatResponse)
async def create_public_widget_chat_message(
    request: Request,
    form_data: PublicWidgetChatForm,
    token: Optional[str] = None,
    db: AsyncSession = Depends(get_async_session),
):
    widget, _ = await _get_public_widget(request, db, token=token, widget_id=form_data.widget_id)

    session = None
    if form_data.session_id:
        session = await ChatWidgetSessions.get_session_by_id_and_widget_id(form_data.session_id, widget.id, db=db)

    if not session:
        session = await ChatWidgetSessions.insert_new_session(
            widget.id,
            ChatWidgetSessionForm(
                visitor_id=form_data.visitor_id or str(uuid4()),
                model_id=widget.model_id,
            ),
            db=db,
        )

    message = await ChatWidgetMessages.insert_new_message(
        session.id,
        widget.id,
        ChatWidgetMessageForm(
            role='user',
            content=form_data.message,
            model_id=widget.model_id,
        ),
        db=db,
    )

    return PublicWidgetChatResponse(
        widget_id=widget.id,
        session_id=session.id,
        message_id=message.id,
    )


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
