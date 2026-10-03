"""Chat widget models, forms, and database operations."""

from __future__ import annotations

import secrets
import re
import time
import uuid
from urllib.parse import urlparse
from typing import Any, Literal, Optional

from open_webui.internal.db import Base, get_async_db_context
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import JSON, BigInteger, Boolean, Column, ForeignKey, Index, Text, delete, select
from sqlalchemy.ext.asyncio import AsyncSession


def generate_widget_token() -> str:
    return f'wgt_{secrets.token_urlsafe(32)}'


def normalize_allowed_domains(value: list[str] | None) -> list[str]:
    domains = []
    for domain in value or []:
        candidate = domain.strip().lower()
        if not candidate:
            continue

        parsed = urlparse(candidate if '://' in candidate else f'//{candidate}', scheme='https')
        host = parsed.hostname or candidate.split('/', 1)[0].split(':', 1)[0]
        normalized = (host or '').strip('.')

        if normalized == '*':
            return ['*']

        if normalized.startswith('*.'):
            suffix = normalized[2:]
            if not _is_valid_domain(suffix):
                raise ValueError(f'Invalid allowed domain: {domain}')
        elif not _is_valid_domain(normalized):
            raise ValueError(f'Invalid allowed domain: {domain}')

        if normalized not in domains:
            domains.append(normalized)

    if len(domains) > 100:
        raise ValueError('A widget can have at most 100 allowed domains')
    return domains


def _is_valid_domain(domain: str) -> bool:
    if not domain or len(domain) > 253:
        return False
    if domain == 'localhost':
        return True
    labels = domain.split('.')
    if any(not label or len(label) > 63 for label in labels):
        return False
    return all(label.replace('-', '').isalnum() and not label.startswith('-') and not label.endswith('-') for label in labels)


HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')
AVATAR_DATA_URL_RE = re.compile(r'^data:image/(png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+$')
AVATAR_MAX_LENGTH = 150_000
MCP_TOOL_ID_PREFIX = 'server:mcp:'
MAX_MCP_TOOL_IDS = 20


class ChatWidgetTheme(BaseModel):
    model_config = ConfigDict(extra='forbid')

    primary_color: str = '#111827'
    primary_text_color: str = '#ffffff'
    header_background_color: str = '#ffffff'
    header_text_color: str = '#111827'
    background_color: str = '#fafafa'
    assistant_bubble_color: str = '#ffffff'
    assistant_text_color: str = '#111827'
    user_bubble_color: str = '#111827'
    user_text_color: str = '#ffffff'

    font_family: Literal['system', 'arial', 'verdana', 'tahoma', 'trebuchet', 'georgia', 'times', 'courier'] = 'system'
    font_size: int = Field(default=14, ge=12, le=20)

    panel_radius: int = Field(default=12, ge=0, le=24)
    bubble_radius: int = Field(default=12, ge=0, le=24)
    panel_width: int = Field(default=390, ge=300, le=480)
    panel_height: int = Field(default=640, ge=400, le=760)

    launcher_shape: Literal['circle', 'rounded', 'square'] = 'circle'
    launcher_size: int = Field(default=58, ge=44, le=72)
    launcher_icon: Literal['chat', 'avatar'] = 'chat'

    position: Literal['right', 'left'] = 'right'
    offset_x: int = Field(default=20, ge=0, le=120)
    offset_y: int = Field(default=20, ge=0, le=120)

    avatar_url: Optional[str] = None
    header_title: Optional[str] = Field(default=None, max_length=60)
    header_subtitle: Optional[str] = Field(default=None, max_length=80)
    input_placeholder: str = Field(default='Type a message', min_length=1, max_length=120)
    show_status: bool = True

    @field_validator(
        'primary_color',
        'primary_text_color',
        'header_background_color',
        'header_text_color',
        'background_color',
        'assistant_bubble_color',
        'assistant_text_color',
        'user_bubble_color',
        'user_text_color',
    )
    @classmethod
    def validate_color(cls, value: str) -> str:
        if not HEX_COLOR_RE.match(value or ''):
            raise ValueError('Colors must be in #RRGGBB format')
        return value.lower()

    @field_validator('avatar_url')
    @classmethod
    def validate_avatar(cls, value: Optional[str]) -> Optional[str]:
        if value is None or value == '':
            return None
        if len(value) > AVATAR_MAX_LENGTH or not AVATAR_DATA_URL_RE.match(value):
            raise ValueError('Avatar must be a PNG, JPEG, WEBP or GIF image under 150 KB')
        return value

    @field_validator('header_title', 'header_subtitle')
    @classmethod
    def blank_to_none(cls, value: Optional[str]) -> Optional[str]:
        value = (value or '').strip()
        return value or None

    @field_validator('input_placeholder')
    @classmethod
    def strip_placeholder(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError('Placeholder cannot be empty')
        return value


def normalize_mcp_tool_ids(value: list[str] | None) -> list[str]:
    ids = []
    for tool_id in value or []:
        tool_id = (tool_id or '').strip()
        if not tool_id:
            continue
        if not tool_id.startswith(MCP_TOOL_ID_PREFIX):
            raise ValueError(f'Invalid MCP tool id: {tool_id}')
        if tool_id not in ids:
            ids.append(tool_id)
    if len(ids) > MAX_MCP_TOOL_IDS:
        raise ValueError(f'A widget can use at most {MAX_MCP_TOOL_IDS} MCP servers')
    return ids


class ChatWidget(Base):
    __tablename__ = 'chat_widget'

    id = Column(Text, primary_key=True, unique=True)
    user_id = Column(Text, nullable=False, index=True)
    name = Column(Text, nullable=False)
    model_id = Column(Text, nullable=False, index=True)
    system_prompt = Column(Text, nullable=True)
    welcome_message = Column(Text, nullable=True)
    token = Column(Text, nullable=False, unique=True, index=True)
    enabled = Column(Boolean, nullable=False, default=True, index=True)
    allowed_domains = Column(JSON, nullable=True)
    theme = Column(JSON, nullable=True)
    mcp_enabled = Column(Boolean, nullable=False, default=False)
    mcp_tool_ids = Column(JSON, nullable=True)
    folder_id = Column(Text, nullable=True)
    knowledge_id = Column(Text, nullable=True)
    created_at = Column(BigInteger, nullable=False, index=True)
    updated_at = Column(BigInteger, nullable=False, index=True)

    __table_args__ = (
        Index('chat_widget_user_updated_idx', 'user_id', 'updated_at'),
        Index('chat_widget_user_enabled_idx', 'user_id', 'enabled'),
    )


class ChatWidgetSession(Base):
    __tablename__ = 'chat_widget_session'

    id = Column(Text, primary_key=True, unique=True)
    widget_id = Column(Text, ForeignKey('chat_widget.id', ondelete='CASCADE'), nullable=False, index=True)
    visitor_id = Column(Text, nullable=False, index=True)
    title = Column(Text, nullable=True)
    model_id = Column(Text, nullable=True, index=True)
    message_count = Column(BigInteger, nullable=False, default=0)
    chat_id = Column(Text, nullable=True, index=True)
    chat_last_message_id = Column(Text, nullable=True)
    created_at = Column(BigInteger, nullable=False, index=True)
    updated_at = Column(BigInteger, nullable=False, index=True)
    last_activity_at = Column(BigInteger, nullable=False, index=True)

    __table_args__ = (
        Index('chat_widget_session_widget_updated_idx', 'widget_id', 'updated_at'),
        Index('chat_widget_session_widget_visitor_idx', 'widget_id', 'visitor_id'),
    )


class ChatWidgetMessage(Base):
    __tablename__ = 'chat_widget_message'

    id = Column(Text, primary_key=True, unique=True)
    session_id = Column(Text, ForeignKey('chat_widget_session.id', ondelete='CASCADE'), nullable=False, index=True)
    widget_id = Column(Text, ForeignKey('chat_widget.id', ondelete='CASCADE'), nullable=False, index=True)
    role = Column(Text, nullable=False)
    content = Column(JSON, nullable=True)
    model_id = Column(Text, nullable=True, index=True)
    done = Column(Boolean, nullable=False, default=True)
    error = Column(JSON, nullable=True)
    usage = Column(JSON, nullable=True)
    created_at = Column(BigInteger, nullable=False, index=True)
    updated_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        Index('chat_widget_message_session_created_idx', 'session_id', 'created_at'),
        Index('chat_widget_message_widget_created_idx', 'widget_id', 'created_at'),
    )


class ChatWidgetModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    name: str
    model_id: str
    system_prompt: Optional[str] = None
    welcome_message: Optional[str] = None
    token: str
    enabled: bool = True
    allowed_domains: Optional[list[str]] = None
    theme: ChatWidgetTheme = Field(default_factory=ChatWidgetTheme)
    mcp_enabled: bool = False
    mcp_tool_ids: list[str] = Field(default_factory=list)
    folder_id: Optional[str] = None
    knowledge_id: Optional[str] = None
    created_at: int
    updated_at: int

    @field_validator('theme', mode='before')
    @classmethod
    def default_theme(cls, value):
        return value or {}

    @field_validator('mcp_tool_ids', mode='before')
    @classmethod
    def default_mcp_tool_ids(cls, value):
        return value or []


class ChatWidgetSessionModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    widget_id: str
    visitor_id: str
    title: Optional[str] = None
    model_id: Optional[str] = None
    message_count: int = 0
    chat_id: Optional[str] = None
    chat_last_message_id: Optional[str] = None
    created_at: int
    updated_at: int
    last_activity_at: int


class ChatWidgetMessageModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    widget_id: str
    role: str
    content: Optional[Any] = None
    model_id: Optional[str] = None
    done: bool = True
    error: Optional[dict | str] = None
    usage: Optional[dict] = None
    created_at: int
    updated_at: int


class ChatWidgetForm(BaseModel):
    name: str
    model_id: str
    system_prompt: Optional[str] = None
    welcome_message: Optional[str] = None
    enabled: bool = True
    allowed_domains: list[str] = Field(default_factory=list)
    theme: ChatWidgetTheme = Field(default_factory=ChatWidgetTheme)
    mcp_enabled: bool = False
    mcp_tool_ids: list[str] = Field(default_factory=list)
    model_config = ConfigDict(extra='forbid')

    @field_validator('allowed_domains')
    @classmethod
    def normalize_allowed_domains(cls, value: list[str]) -> list[str]:
        return normalize_allowed_domains(value)

    @field_validator('mcp_tool_ids')
    @classmethod
    def normalize_mcp_tool_ids(cls, value: list[str]) -> list[str]:
        return normalize_mcp_tool_ids(value)


class ChatWidgetUpdateForm(BaseModel):
    name: Optional[str] = None
    model_id: Optional[str] = None
    system_prompt: Optional[str] = None
    welcome_message: Optional[str] = None
    enabled: Optional[bool] = None
    allowed_domains: Optional[list[str]] = None
    theme: Optional[ChatWidgetTheme] = None
    mcp_enabled: Optional[bool] = None
    mcp_tool_ids: Optional[list[str]] = None
    model_config = ConfigDict(extra='forbid')

    @field_validator('allowed_domains')
    @classmethod
    def normalize_allowed_domains(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return None
        return normalize_allowed_domains(value)

    @field_validator('mcp_tool_ids')
    @classmethod
    def normalize_mcp_tool_ids(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return None
        return normalize_mcp_tool_ids(value)


class ChatWidgetSessionForm(BaseModel):
    visitor_id: str
    title: Optional[str] = None
    model_id: Optional[str] = None
    model_config = ConfigDict(extra='forbid')


class ChatWidgetMessageForm(BaseModel):
    role: str
    content: Optional[Any] = None
    model_id: Optional[str] = None
    done: bool = True
    error: Optional[dict | str] = None
    usage: Optional[dict] = None
    model_config = ConfigDict(extra='forbid')


class ChatWidgetTable:
    async def insert_new_widget(
        self,
        user_id: str,
        form_data: ChatWidgetForm,
        db: Optional[AsyncSession] = None,
    ) -> ChatWidgetModel:
        async with get_async_db_context(db) as db:
            now = int(time.time())
            widget = ChatWidget(
                id=str(uuid.uuid4()),
                user_id=user_id,
                token=generate_widget_token(),
                created_at=now,
                updated_at=now,
                **form_data.model_dump(),
            )
            db.add(widget)
            await db.commit()
            await db.refresh(widget)
            return ChatWidgetModel.model_validate(widget)

    async def get_widget_by_id(self, id: str, db: Optional[AsyncSession] = None) -> Optional[ChatWidgetModel]:
        async with get_async_db_context(db) as db:
            widget = await db.get(ChatWidget, id)
            return ChatWidgetModel.model_validate(widget) if widget else None

    async def get_widget_by_id_and_user_id(
        self, id: str, user_id: str, db: Optional[AsyncSession] = None
    ) -> Optional[ChatWidgetModel]:
        async with get_async_db_context(db) as db:
            result = await db.execute(select(ChatWidget).filter_by(id=id, user_id=user_id))
            widget = result.scalars().first()
            return ChatWidgetModel.model_validate(widget) if widget else None

    async def get_widget_by_token(self, token: str, db: Optional[AsyncSession] = None) -> Optional[ChatWidgetModel]:
        async with get_async_db_context(db) as db:
            result = await db.execute(select(ChatWidget).filter_by(token=token))
            widget = result.scalars().first()
            return ChatWidgetModel.model_validate(widget) if widget else None

    async def get_widgets_by_user_id(
        self, user_id: str, db: Optional[AsyncSession] = None
    ) -> list[ChatWidgetModel]:
        async with get_async_db_context(db) as db:
            result = await db.execute(
                select(ChatWidget).filter_by(user_id=user_id).order_by(ChatWidget.updated_at.desc())
            )
            return [ChatWidgetModel.model_validate(widget) for widget in result.scalars().all()]

    async def update_widget_by_id_and_user_id(
        self,
        id: str,
        user_id: str,
        form_data: ChatWidgetUpdateForm,
        db: Optional[AsyncSession] = None,
    ) -> Optional[ChatWidgetModel]:
        async with get_async_db_context(db) as db:
            result = await db.execute(select(ChatWidget).filter_by(id=id, user_id=user_id))
            widget = result.scalars().first()
            if not widget:
                return None

            data = form_data.model_dump(exclude_unset=True)
            for key, value in data.items():
                setattr(widget, key, value)
            widget.updated_at = int(time.time())

            await db.commit()
            await db.refresh(widget)
            return ChatWidgetModel.model_validate(widget)

    async def rotate_token_by_id_and_user_id(
        self,
        id: str,
        user_id: str,
        db: Optional[AsyncSession] = None,
    ) -> Optional[ChatWidgetModel]:
        async with get_async_db_context(db) as db:
            result = await db.execute(select(ChatWidget).filter_by(id=id, user_id=user_id))
            widget = result.scalars().first()
            if not widget:
                return None

            widget.token = generate_widget_token()
            widget.updated_at = int(time.time())

            await db.commit()
            await db.refresh(widget)
            return ChatWidgetModel.model_validate(widget)

    async def delete_widget_by_id_and_user_id(
        self, id: str, user_id: str, db: Optional[AsyncSession] = None
    ) -> bool:
        async with get_async_db_context(db) as db:
            result = await db.execute(delete(ChatWidget).where(ChatWidget.id == id, ChatWidget.user_id == user_id))
            await db.commit()
            return result.rowcount > 0

    async def set_folder_id(self, id: str, folder_id: Optional[str], db: Optional[AsyncSession] = None) -> None:
        async with get_async_db_context(db) as db:
            widget = await db.get(ChatWidget, id)
            if widget:
                widget.folder_id = folder_id
                await db.commit()

    async def set_knowledge_id(
        self, id: str, knowledge_id: Optional[str], db: Optional[AsyncSession] = None
    ) -> None:
        async with get_async_db_context(db) as db:
            widget = await db.get(ChatWidget, id)
            if widget:
                widget.knowledge_id = knowledge_id
                await db.commit()


class ChatWidgetSessionTable:
    async def insert_new_session(
        self,
        widget_id: str,
        form_data: ChatWidgetSessionForm,
        db: Optional[AsyncSession] = None,
    ) -> ChatWidgetSessionModel:
        async with get_async_db_context(db) as db:
            now = int(time.time())
            session = ChatWidgetSession(
                id=str(uuid.uuid4()),
                widget_id=widget_id,
                message_count=0,
                created_at=now,
                updated_at=now,
                last_activity_at=now,
                **form_data.model_dump(),
            )
            db.add(session)
            await db.commit()
            await db.refresh(session)
            return ChatWidgetSessionModel.model_validate(session)

    async def get_session_by_id(
        self, id: str, db: Optional[AsyncSession] = None
    ) -> Optional[ChatWidgetSessionModel]:
        async with get_async_db_context(db) as db:
            session = await db.get(ChatWidgetSession, id)
            return ChatWidgetSessionModel.model_validate(session) if session else None

    async def get_session_by_id_and_widget_id(
        self, id: str, widget_id: str, db: Optional[AsyncSession] = None
    ) -> Optional[ChatWidgetSessionModel]:
        async with get_async_db_context(db) as db:
            result = await db.execute(select(ChatWidgetSession).filter_by(id=id, widget_id=widget_id))
            session = result.scalars().first()
            return ChatWidgetSessionModel.model_validate(session) if session else None

    async def get_sessions_by_widget_id(
        self,
        widget_id: str,
        skip: int = 0,
        limit: int = 50,
        db: Optional[AsyncSession] = None,
    ) -> list[ChatWidgetSessionModel]:
        async with get_async_db_context(db) as db:
            result = await db.execute(
                select(ChatWidgetSession)
                .filter_by(widget_id=widget_id)
                .order_by(ChatWidgetSession.last_activity_at.desc())
                .offset(skip)
                .limit(limit)
            )
            return [ChatWidgetSessionModel.model_validate(session) for session in result.scalars().all()]

    async def update_chat_link(
        self,
        id: str,
        chat_id: Optional[str] = None,
        chat_last_message_id: Optional[str] = None,
        db: Optional[AsyncSession] = None,
    ) -> None:
        async with get_async_db_context(db) as db:
            session = await db.get(ChatWidgetSession, id)
            if not session:
                return
            if chat_id is not None:
                session.chat_id = chat_id
            if chat_last_message_id is not None:
                session.chat_last_message_id = chat_last_message_id
            await db.commit()

    async def delete_session_by_id_and_widget_id(
        self,
        id: str,
        widget_id: str,
        db: Optional[AsyncSession] = None,
    ) -> bool:
        async with get_async_db_context(db) as db:
            await db.execute(
                delete(ChatWidgetMessage).where(
                    ChatWidgetMessage.session_id == id,
                    ChatWidgetMessage.widget_id == widget_id,
                )
            )
            result = await db.execute(
                delete(ChatWidgetSession).where(
                    ChatWidgetSession.id == id,
                    ChatWidgetSession.widget_id == widget_id,
                )
            )
            await db.commit()
            return result.rowcount > 0


class ChatWidgetMessageTable:
    async def insert_new_message(
        self,
        session_id: str,
        widget_id: str,
        form_data: ChatWidgetMessageForm,
        db: Optional[AsyncSession] = None,
    ) -> ChatWidgetMessageModel:
        async with get_async_db_context(db) as db:
            now = int(time.time())
            message = ChatWidgetMessage(
                id=str(uuid.uuid4()),
                session_id=session_id,
                widget_id=widget_id,
                created_at=now,
                updated_at=now,
                **form_data.model_dump(),
            )
            db.add(message)

            result = await db.execute(select(ChatWidgetSession).filter_by(id=session_id, widget_id=widget_id))
            session = result.scalars().first()
            if session:
                session.message_count = (session.message_count or 0) + 1
                session.updated_at = now
                session.last_activity_at = now

            await db.commit()
            await db.refresh(message)
            return ChatWidgetMessageModel.model_validate(message)

    async def get_messages_by_session_id(
        self, session_id: str, db: Optional[AsyncSession] = None
    ) -> list[ChatWidgetMessageModel]:
        async with get_async_db_context(db) as db:
            result = await db.execute(
                select(ChatWidgetMessage)
                .filter_by(session_id=session_id)
                .order_by(ChatWidgetMessage.created_at.asc())
            )
            return [ChatWidgetMessageModel.model_validate(message) for message in result.scalars().all()]

    async def get_messages_by_session_id_and_widget_id(
        self,
        session_id: str,
        widget_id: str,
        db: Optional[AsyncSession] = None,
    ) -> list[ChatWidgetMessageModel]:
        async with get_async_db_context(db) as db:
            result = await db.execute(
                select(ChatWidgetMessage)
                .filter_by(session_id=session_id, widget_id=widget_id)
                .order_by(ChatWidgetMessage.created_at.asc())
            )
            return [ChatWidgetMessageModel.model_validate(message) for message in result.scalars().all()]


ChatWidgets = ChatWidgetTable()
ChatWidgetSessions = ChatWidgetSessionTable()
ChatWidgetMessages = ChatWidgetMessageTable()
