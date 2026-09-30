"""Chat widget models, forms, and database operations."""

from __future__ import annotations

import secrets
import time
import uuid
from urllib.parse import urlparse
from typing import Any, Optional

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
    created_at: int
    updated_at: int


class ChatWidgetSessionModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    widget_id: str
    visitor_id: str
    title: Optional[str] = None
    model_id: Optional[str] = None
    message_count: int = 0
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
    model_config = ConfigDict(extra='forbid')

    @field_validator('allowed_domains')
    @classmethod
    def normalize_allowed_domains(cls, value: list[str]) -> list[str]:
        return normalize_allowed_domains(value)


class ChatWidgetUpdateForm(BaseModel):
    name: Optional[str] = None
    model_id: Optional[str] = None
    system_prompt: Optional[str] = None
    welcome_message: Optional[str] = None
    enabled: Optional[bool] = None
    allowed_domains: Optional[list[str]] = None
    model_config = ConfigDict(extra='forbid')

    @field_validator('allowed_domains')
    @classmethod
    def normalize_allowed_domains(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return None
        return normalize_allowed_domains(value)


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


ChatWidgets = ChatWidgetTable()
ChatWidgetSessions = ChatWidgetSessionTable()
ChatWidgetMessages = ChatWidgetMessageTable()
