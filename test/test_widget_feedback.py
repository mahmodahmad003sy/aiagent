"""Focused database/API tests without starting the model-serving application.

Load the production model and endpoint definitions with isolated dependencies so
these tests never initialize or migrate the developer's real application DB.
Run: python -m unittest discover -s test -p test_widget_feedback.py
"""
import ast
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, Optional
from unittest.mock import AsyncMock

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import JSON, BigInteger, Boolean, Column, ForeignKey, Index, Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base, aliased
from starlette.responses import Response

ROOT = Path(__file__).resolve().parents[1]


def definitions(path, names, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    tree.body = [node for node in tree.body if getattr(node, 'name', '') in names]
    exec(compile(tree, path, 'exec'), namespace)


class FeedbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ns = dict(globals(), Base=declarative_base(), router=APIRouter(), DEFAULT_SESSION_IDLE_MINUTES=30,
                       get_async_session=lambda: None, get_verified_user=lambda: None,
                       ERROR_MESSAGES=SimpleNamespace(NOT_FOUND='Not found'),
                       _ensure_public_request_size=lambda _: None,
                       _set_public_cors_headers=lambda *args: None,
                       _ensure_public_rate_limit=AsyncMock())
        definitions('backend/open_webui/models/chat_widgets.py',
                    {'ChatWidget', 'ChatWidgetSession', 'ChatWidgetMessage', 'ChatWidgetMessageModel'},
                    self.ns)
        self.widget = SimpleNamespace(id='widget')
        self.session = SimpleNamespace(id='session', visitor_id='visitor')
        self.ns.update(_get_public_widget=AsyncMock(return_value=(self.widget, None)),
                       ChatWidgets=SimpleNamespace(get_widget_for_user=AsyncMock(return_value=self.widget)),
                       ChatWidgetSessions=SimpleNamespace(get_session_by_id_and_widget_id=AsyncMock(return_value=self.session)))
        definitions('backend/open_webui/routers/widgets.py',
                    {'PublicWidgetSessionResumeForm', 'PublicWidgetFeedbackForm',
                     'save_public_widget_feedback', 'get_widget_feedback'}, self.ns)
        self.engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        async with self.engine.begin() as conn:
            await conn.run_sync(self.ns['Base'].metadata.create_all)
        self.db = async_sessionmaker(self.engine, expire_on_commit=False)()
        model = self.ns['ChatWidgetMessage']
        self.db.add(self.ns['ChatWidgetSession'](id='session', widget_id='widget', visitor_id='visitor',
                    created_at=1, updated_at=2, last_activity_at=2))
        self.db.add_all([
            model(id='question', session_id='session', widget_id='widget', role='user', content='Question?', created_at=1, updated_at=1),
            model(id='answer', parent_message_id='question', session_id='session', widget_id='widget', role='assistant', content='Answer.', done=True, created_at=2, updated_at=2),
            model(id='other', session_id='other-session', widget_id='other-widget', role='assistant', content='Private', done=True, feedback_vote=-1, created_at=3, updated_at=3)
        ])
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    def form(self, **overrides):
        return self.ns['PublicWidgetFeedbackForm'](**dict(
            dict(widget_id='widget', session_id='session', visitor_id='visitor', message_id='answer', vote=1), **overrides))

    async def save(self, **overrides):
        return await self.ns['save_public_widget_feedback'](None, self.form(**overrides), Response(), db=self.db)

    async def review(self, **overrides):
        return await self.ns['get_widget_feedback']('widget', db=self.db, user=None,
                                                  **dict(dict(vote=None, skip=0, limit=25), **overrides))

    async def test_optional_details_update_and_filter_with_question(self):
        result = await self.save()
        self.assertEqual(result['vote'], 1)
        self.assertIsNone(result['score'])
        await self.save(vote=-1, score=2, comment='  Incorrect answer  ')
        rows = await self.review(vote='-1')
        self.assertEqual(len(rows['items']), 1)
        self.assertEqual(rows['items'][0]['question'].content, 'Question?')
        self.assertEqual(rows['items'][0]['answer'].feedback['comment'], 'Incorrect answer')
        self.assertEqual((await self.review(vote='1'))['items'], [])
        self.assertEqual((await self.review(skip=1))['items'], [])

    async def test_rejects_other_visitors_sessions_and_nonanswers(self):
        for overrides in [{'visitor_id': 'intruder'}, {'message_id': 'other'}, {'message_id': 'question'}]:
            with self.subTest(overrides=overrides), self.assertRaises(HTTPException) as caught:
                await self.save(**overrides)
            self.assertEqual(caught.exception.status_code, 404)
        answer = await self.db.get(self.ns['ChatWidgetMessage'], 'answer')
        answer.error = {'content': 'failed'}
        with self.assertRaises(HTTPException):
            await self.save()
        answer.error = None
        answer.done = False
        with self.assertRaises(HTTPException):
            await self.save()

    async def test_review_requires_owner_access(self):
        self.ns['ChatWidgets'].get_widget_for_user.return_value = None
        with self.assertRaises(HTTPException) as caught:
            await self.review()
        self.assertEqual(caught.exception.status_code, 404)

    async def test_validation(self):
        for invalid in [{'vote': 0}, {'score': 6}, {'score': 1.5}, {'comment': 'x' * 2001}]:
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                self.form(**invalid)

    async def test_http_filter_and_pagination_validation(self):
        await self.save(vote=-1)
        app = FastAPI()
        app.include_router(self.ns['router'])
        app.dependency_overrides[self.ns['get_async_session']] = lambda: self.db
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.get('/widget/feedback?vote=-1')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['items'][0]['question']['content'], 'Question?')
            for query in ['vote=0', 'limit=101', 'skip=-1']:
                self.assertEqual((await client.get('/widget/feedback?' + query)).status_code, 422)


if __name__ == '__main__':
    unittest.main()
