from __future__ import annotations

import asyncio
import time
from datetime import timedelta
from typing import Optional
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.internal.db import get_async_session
from open_webui.models.chat_widgets import (
    ChatWidgetTheme,
    ChatWidgetMessageForm,
    ChatWidgetMessageModel,
    ChatWidgetMessages,
    ChatWidgetForm,
    ChatWidgetModel,
    ChatWidgetSessionForm,
    ChatWidgetSessionModel,
    ChatWidgetSessions,
    ChatWidgets,
    ChatWidgetUpdateForm,
    MCP_TOOL_ID_PREFIX,
)
from open_webui.models.chat_widget_crawl import (
    ChatWidgetCrawlConfigs,
    ChatWidgetCrawlRuns,
    ChatWidgetKnowledgeItems,
)
from open_webui.models.chats import ChatForm, Chats
from open_webui.models.folders import FolderForm, Folders
from open_webui.models.users import Users
from open_webui.utils.auth import create_token, get_verified_user
from open_webui.utils.json_codec import JSONCodec
from open_webui.utils.models import get_all_models, get_filtered_models
from open_webui.utils.rate_limit import RateLimiter
from open_webui.utils.redis import get_redis_client
from open_webui.utils.widget_crawl_jobs import request_cancel as request_widget_job_cancel
from open_webui.utils.widget_knowledge_sync import delete_widget_knowledge
from open_webui.utils.widget_stream import (
    WIDGET_ERROR_MESSAGE,
    register_widget_turn,
    unregister_widget_turn,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response, StreamingResponse

router = APIRouter()

PUBLIC_WIDGET_CHAT_MESSAGE_LIMIT = 20_000
PUBLIC_WIDGET_REQUEST_BODY_LIMIT = 64 * 1024
PUBLIC_WIDGET_CHAT_RATE_LIMIT = 60
PUBLIC_WIDGET_VISITOR_RATE_LIMIT = 20
PUBLIC_WIDGET_RATE_LIMIT_WINDOW = 60
PUBLIC_WIDGET_STREAM_KEEPALIVE = 15
WIDGET_OWNER_TOKEN_TTL = timedelta(minutes=15)
WIDGET_FOLDER_PREFIX = 'Widget: '
WIDGET_KNOWLEDGE_INSTRUCTION = (
    'Use the provided website knowledge to answer. Some knowledge entries describe downloadable resources '
    '(link only): you may tell the user the resource exists and share its URL and the page where it was found, '
    'but never claim to know what is inside it.'
)

public_widget_chat_rate_limiter = RateLimiter(
    redis_client=get_redis_client(),
    limit=PUBLIC_WIDGET_CHAT_RATE_LIMIT,
    window=PUBLIC_WIDGET_RATE_LIMIT_WINDOW,
    bucket_size=10,
)
public_widget_visitor_rate_limiter = RateLimiter(
    redis_client=get_redis_client(),
    limit=PUBLIC_WIDGET_VISITOR_RATE_LIMIT,
    window=PUBLIC_WIDGET_RATE_LIMIT_WINDOW,
    bucket_size=10,
)


class PublicWidgetConfigResponse(BaseModel):
    id: str
    name: str
    welcome_message: Optional[str] = None
    theme: ChatWidgetTheme


class PublicWidgetChatForm(BaseModel):
    message: str = Field(min_length=1, max_length=PUBLIC_WIDGET_CHAT_MESSAGE_LIMIT)
    widget_id: Optional[str] = Field(default=None, max_length=128)
    session_id: Optional[str] = Field(default=None, max_length=128)
    visitor_id: Optional[str] = Field(default=None, max_length=128)
    stream: bool = False
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
    assistant_message_id: Optional[str] = None
    content: Optional[str] = None
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


async def _ensure_mcp_tool_access(request: Request, tool_ids: list[str], user, db: AsyncSession) -> None:
    if not tool_ids:
        return
    from open_webui.routers.tools import get_tools as list_user_tools

    available = {
        tool.id
        for tool in await list_user_tools(request, query=None, user=user, db=db)
        if tool.id.startswith(MCP_TOOL_ID_PREFIX)
    }
    missing = [tool_id for tool_id in tool_ids if tool_id not in available]
    if missing:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f'MCP server not available: {missing[0]}')


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


def _client_key(request: Request) -> str:
    forwarded_for = request.headers.get('x-forwarded-for')
    if forwarded_for:
        return forwarded_for.split(',', 1)[0].strip()
    return request.client.host if request.client else 'unknown'


def _ensure_public_request_size(request: Request) -> None:
    content_length = request.headers.get('content-length')
    if not content_length:
        return
    try:
        size = int(content_length)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=ERROR_MESSAGES.INCORRECT_FORMAT())
    if size > PUBLIC_WIDGET_REQUEST_BODY_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=ERROR_MESSAGES.INPUT_TOO_LONG(PUBLIC_WIDGET_REQUEST_BODY_LIMIT),
        )


def _ensure_public_rate_limit(request: Request, widget: ChatWidgetModel, visitor_id: Optional[str]) -> None:
    widget_key = f'chat_widget:{widget.id}'
    visitor_key = f'{widget_key}:{visitor_id or _client_key(request)}'
    if public_widget_chat_rate_limiter.is_limited(widget_key) or public_widget_visitor_rate_limiter.is_limited(
        visitor_key
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=ERROR_MESSAGES.RATE_LIMIT_EXCEEDED,
        )


def _set_public_cors_headers(response: Response, request: Request, widget: ChatWidgetModel | None = None) -> None:
    origin = request.headers.get('origin')
    if not origin:
        response.headers.setdefault('Access-Control-Allow-Origin', '*')
    elif widget is None or not widget.allowed_domains or any(
        _domain_matches(_domain_from_value(origin) or '', allowed_domain) for allowed_domain in widget.allowed_domains
    ):
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Vary'] = 'Origin'

    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'authorization,content-type,x-widget-token'
    response.headers['Access-Control-Max-Age'] = '600'


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
    if len(widget_token) > 256:
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


def _message_content_as_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get('text') or item.get('content')
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        return ''.join(parts)
    return '' if content is None else str(content)


async def _ensure_widget_folder(widget: ChatWidgetModel) -> str:
    if widget.folder_id and await Folders.get_folder_by_id_and_user_id(widget.folder_id, widget.user_id):
        return widget.folder_id

    name = f'{WIDGET_FOLDER_PREFIX}{widget.name}'[:100]
    folder = await Folders.get_folder_by_parent_id_and_user_id_and_name(None, widget.user_id, name)
    if not folder:
        folder = await Folders.insert_new_folder(widget.user_id, FolderForm(name=name), None)
    await ChatWidgets.set_folder_id(widget.id, folder.id)
    return folder.id


def _chat_title(text: str) -> str:
    title = ' '.join((text or '').split())
    return (title[:57] + '...') if len(title) > 60 else (title or 'Widget chat')


async def _ensure_session_chat(
    widget: ChatWidgetModel,
    session: ChatWidgetSessionModel,
    first_message: str,
) -> tuple[str, Optional[str]]:
    """Return (chat_id, parent_message_id) for the next user message."""
    if session.chat_id and await Chats.get_chat_by_id_and_user_id(session.chat_id, widget.user_id):
        return session.chat_id, session.chat_last_message_id

    folder_id = await _ensure_widget_folder(widget)

    # Backfill sessions created before V2 or sessions whose owner chat was deleted.
    existing = await ChatWidgetMessages.get_messages_by_session_id_and_widget_id(session.id, widget.id)
    history: dict[str, dict] = {}
    flat: list[dict] = []
    last_id: Optional[str] = None
    first_user_text = None
    for message in existing:
        if message.role not in {'user', 'assistant'}:
            continue
        content = _message_content_as_text(message.content)
        if message.role == 'user' and first_user_text is None:
            first_user_text = content
        message_id = str(uuid4())
        history[message_id] = {
            'id': message_id,
            'parentId': last_id,
            'childrenIds': [],
            'role': message.role,
            'content': content,
            'timestamp': message.created_at,
            **(
                {'model': widget.model_id, 'done': True}
                if message.role == 'assistant'
                else {'models': [widget.model_id]}
            ),
        }
        if last_id:
            history[last_id]['childrenIds'].append(message_id)
        flat.append({'role': message.role, 'content': content})
        last_id = message_id

    chat_id = str(uuid4())
    await Chats.insert_new_chat(
        chat_id,
        widget.user_id,
        ChatForm(
            folder_id=folder_id,
            chat={
                'id': chat_id,
                'title': _chat_title(first_user_text or first_message),
                'models': [widget.model_id],
                'history': {'currentId': last_id, 'messages': history},
                'messages': flat,
                'tags': [],
                'timestamp': int(time.time() * 1000),
                'meta': {
                    'widget_id': widget.id,
                    'widget_session_id': session.id,
                    'visitor_id': session.visitor_id,
                },
            },
        ),
    )
    await ChatWidgetSessions.update_chat_link(session.id, chat_id=chat_id, chat_last_message_id=last_id)

    from open_webui.socket.main import sio

    await sio.emit(
        'events',
        {'chat_id': chat_id, 'message_id': None, 'data': {'type': 'chat:list'}},
        room=f'user:{widget.user_id}',
    )
    return chat_id, last_id


async def _save_assistant_message(
    session_id: str,
    widget_id: str,
    model_id: str,
    content: str,
    usage: Optional[dict] = None,
    error: Optional[dict | str] = None,
    db: AsyncSession | None = None,
) -> ChatWidgetMessageModel:
    return await ChatWidgetMessages.insert_new_message(
        session_id,
        widget_id,
        ChatWidgetMessageForm(
            role='assistant',
            content=content,
            model_id=model_id,
            done=True,
            usage=usage,
            error=error,
        ),
        db=db,
    )


@router.post('', response_model=ChatWidgetModel)
async def create_widget(
    request: Request,
    form_data: ChatWidgetForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    await _ensure_model_access(request, form_data.model_id, user, db)
    if form_data.mcp_enabled and not form_data.mcp_tool_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Select at least one MCP server')
    await _ensure_mcp_tool_access(request, form_data.mcp_tool_ids, user, db)
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
    http_response: Response,
    token: Optional[str] = None,
    widget_id: Optional[str] = None,
    db: AsyncSession = Depends(get_async_session),
):
    widget, _ = await _get_public_widget(request, db, token=token, widget_id=widget_id)
    _set_public_cors_headers(http_response, request, widget)
    return PublicWidgetConfigResponse(
        id=widget.id,
        name=widget.name,
        welcome_message=widget.welcome_message,
        theme=widget.theme,
    )


@router.options('/public/{path:path}')
async def public_widget_options(request: Request):
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _set_public_cors_headers(response, request)
    return response


@router.post('/public/chat', response_model=PublicWidgetChatResponse)
async def create_public_widget_chat_message(
    request: Request,
    http_response: Response,
    form_data: PublicWidgetChatForm,
    token: Optional[str] = None,
    db: AsyncSession = Depends(get_async_session),
):
    _ensure_public_request_size(request)
    widget, owner = await _get_public_widget(request, db, token=token, widget_id=form_data.widget_id)
    _ensure_public_rate_limit(request, widget, form_data.visitor_id or form_data.session_id)
    _set_public_cors_headers(http_response, request, widget)

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

    chat_id, parent_message_id = await _ensure_session_chat(widget, session, form_data.message)

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

    user_message_id = str(uuid4())
    assistant_message_id = str(uuid4())

    system_prompt = widget.system_prompt or ''
    if widget.knowledge_id:
        system_prompt = f'{system_prompt}\n\n{WIDGET_KNOWLEDGE_INSTRUCTION}'.strip()

    messages = []
    if system_prompt:
        messages.append({'role': 'system', 'content': system_prompt})
    messages.append({'role': 'user', 'content': form_data.message})

    form_payload = {
        'model': widget.model_id,
        'messages': messages,
        'stream': True,
        'chat_id': chat_id,
        'id': assistant_message_id,
        'user_message': {
            'id': user_message_id,
            'parentId': parent_message_id,
            'childrenIds': [],
            'role': 'user',
            'content': form_data.message,
            'timestamp': int(time.time()),
            'models': [widget.model_id],
        },
        'params': {'tool_approval_mode': 'full'},
        'features': {},
    }
    if widget.mcp_enabled and widget.mcp_tool_ids:
        form_payload['tool_ids'] = list(widget.mcp_tool_ids)
    if widget.knowledge_id:
        form_payload['files'] = [{'type': 'collection', 'id': widget.knowledge_id}]

    request.state.token = create_token(
        data={'id': owner.id, 'typ': 'widget'},
        expires_delta=WIDGET_OWNER_TOKEN_TTL,
    )

    turn = register_widget_turn(assistant_message_id)
    widget_id, session_id, model_id = widget.id, session.id, widget.model_id

    async def run_turn():
        try:
            await request.app.state.CHAT_COMPLETION_HANDLER(request, form_payload, user=owner)
        except HTTPException as exc:
            turn.handle_event({'type': 'chat:message:error', 'data': {'error': {'content': str(exc.detail)}}})
        except Exception as exc:
            turn.handle_event({'type': 'chat:message:error', 'data': {'error': {'content': str(exc)}}})
        finally:
            try:
                await _save_assistant_message(
                    session_id,
                    widget_id,
                    model_id,
                    turn.content,
                    usage=turn.usage,
                    error={'content': turn.error} if turn.error else None,
                    db=None,
                )
                await ChatWidgetSessions.update_chat_link(session_id, chat_last_message_id=assistant_message_id)
            finally:
                unregister_widget_turn(assistant_message_id)
                turn.queue.put_nowait(None)

    task = asyncio.create_task(run_turn())

    if form_data.stream:
        async def event_stream():
            yield f'data: {JSONCodec.dumps({"widget": {"session_id": session_id, "message_id": message.id}})}\n\n'
            while True:
                try:
                    item = await asyncio.wait_for(turn.queue.get(), timeout=PUBLIC_WIDGET_STREAM_KEEPALIVE)
                except asyncio.TimeoutError:
                    yield ': ping\n\n'
                    continue
                if item is None:
                    break
                yield f'data: {JSONCodec.dumps(item)}\n\n'
            yield 'data: [DONE]\n\n'

        stream_response = StreamingResponse(event_stream(), media_type='text/event-stream')
        stream_response.headers['Cache-Control'] = 'no-cache'
        stream_response.headers['X-Accel-Buffering'] = 'no'
        _set_public_cors_headers(stream_response, request, widget)
        return stream_response

    await task
    return PublicWidgetChatResponse(
        widget_id=widget.id,
        session_id=session.id,
        message_id=message.id,
        assistant_message_id=None,
        content=turn.content if not turn.error else WIDGET_ERROR_MESSAGE,
    )


@router.get('/{widget_id}/sessions', response_model=list[ChatWidgetSessionModel])
async def get_widget_sessions(
    widget_id: str,
    skip: int = 0,
    limit: int = 50,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    widget = await ChatWidgets.get_widget_by_id_and_user_id(widget_id, user.id, db=db)
    if not widget:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)

    return await ChatWidgetSessions.get_sessions_by_widget_id(
        widget.id,
        skip=max(skip, 0),
        limit=min(max(limit, 1), 100),
        db=db,
    )


@router.get('/{widget_id}/sessions/{session_id}/messages', response_model=list[ChatWidgetMessageModel])
async def get_widget_session_messages(
    widget_id: str,
    session_id: str,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    widget = await ChatWidgets.get_widget_by_id_and_user_id(widget_id, user.id, db=db)
    if not widget:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)

    session = await ChatWidgetSessions.get_session_by_id_and_widget_id(session_id, widget.id, db=db)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)

    return await ChatWidgetMessages.get_messages_by_session_id_and_widget_id(session.id, widget.id, db=db)


@router.delete('/{widget_id}/sessions/{session_id}', response_model=bool)
async def delete_widget_session(
    widget_id: str,
    session_id: str,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    widget = await ChatWidgets.get_widget_by_id_and_user_id(widget_id, user.id, db=db)
    if not widget:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)

    session = await ChatWidgetSessions.get_session_by_id_and_widget_id(session_id, widget.id, db=db)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)

    if session.chat_id:
        await Chats.delete_chat_by_id_and_user_id(session.chat_id, widget.user_id)

    deleted = await ChatWidgetSessions.delete_session_by_id_and_widget_id(session_id, widget.id, db=db)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)

    return True


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

    existing = await ChatWidgets.get_widget_by_id_and_user_id(widget_id, user.id, db=db)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)
    effective_enabled = form_data.mcp_enabled if form_data.mcp_enabled is not None else existing.mcp_enabled
    effective_ids = form_data.mcp_tool_ids if form_data.mcp_tool_ids is not None else existing.mcp_tool_ids
    if effective_enabled and not effective_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Select at least one MCP server')
    if form_data.mcp_tool_ids is not None:
        await _ensure_mcp_tool_access(request, form_data.mcp_tool_ids, user, db)

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
