import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from starlette.responses import HTMLResponse

path = Path(__file__).resolve().parents[1] / 'backend/open_webui/utils/mcp/widget_bridges.py'
spec = importlib.util.spec_from_file_location('widget_bridges', path)
bridges = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridges)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        bridges._apps.clear()
        self.turn = SimpleNamespace(queue=asyncio.Queue(), allow_apps=True)

    def result(self):
        config = {'appHtml': '<h1>App</h1>', 'toolInput': {'arguments': {'x': 1}},
                  'toolResult': {'content': []}, 'rpc': {'token': 'OWNER_SECRET'}}
        return HTMLResponse('<script>var config = ' + json.dumps(config) + ';</script>'), 'context'

    def test_bridge_tuple_delivers_only_app_data_and_scopes_capability(self):
        text = bridges.register_result(self.result(), 'bridge', 'session', self.turn)
        event = self.turn.queue.get_nowait()
        self.assertNotIn('OWNER_SECRET', str(event) + text)
        app_id = event['widget_bridge_app']['id']
        self.assertEqual(bridges.get_app(app_id, 'session')['tool_id'], 'bridge')
        with self.assertRaises(ValueError):
            bridges.get_app(app_id, 'another-session')
        bridges._apps[app_id]['expires'] = 0
        with self.assertRaises(ValueError):
            bridges.get_app(app_id, 'session')

    def test_nonstream_never_returns_wrapper(self):
        self.turn.allow_apps = False
        result = bridges.register_result(self.result(), 'bridge', 'session', self.turn)
        self.assertIn('streaming', result)
        self.assertNotIn('OWNER_SECRET', result)
        self.assertTrue(self.turn.queue.empty())

    def test_malformed_and_oversized_fail_closed(self):
        for html in ['<script>alert(1)</script>', 'x' * 3_000_001, 'var config = {"appHtml": 1}']:
            self.assertIn('unsupported', bridges.register_result(HTMLResponse(html), 'b', 's', self.turn))
        self.assertTrue(self.turn.queue.empty())

    def test_text_results_preserved(self):
        self.assertEqual(bridges.register_result('tools list', 'b', 's', self.turn), 'tools list')

    def test_discovery_excludes_native_and_unrelated_tools(self):
        for name in ['MCP App Bridge', 'My MCP App Bridge (CRM)']:
            self.assertTrue(bridges.is_app_bridge(SimpleNamespace(id='local', name=name, meta={})))
        self.assertTrue(bridges.is_app_bridge(SimpleNamespace(id='local', name='Renamed', meta={'manifest': {'title': 'MCP App Bridge'}})))
        for tool_id, name in [('server:mcp:test', 'MCP App Bridge'), ('local', 'MCP tools')]:
            self.assertFalse(bridges.is_app_bridge(SimpleNamespace(id=tool_id, name=name, meta={})))



class MigrationTests(unittest.TestCase):
    def test_upgrade_preserves_native_selection_and_downgrade(self):
        from sqlalchemy import create_engine, text
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        migration_path = path.parents[2] / 'migrations/versions/a7d9e2f4b601_widget_mcp_apps.py'
        migration_spec = importlib.util.spec_from_file_location('widget_apps_migration', migration_path)
        migration = importlib.util.module_from_spec(migration_spec)
        migration_spec.loader.exec_module(migration)
        engine = create_engine('sqlite://')
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE chat_widget (id TEXT PRIMARY KEY, mcp_enabled BOOLEAN, mcp_tool_ids JSON)'))
            connection.execute(text("INSERT INTO chat_widget VALUES ('existing', 1, '[\"server:mcp:original\"]')"))
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            row = connection.execute(text('SELECT * FROM chat_widget')).mappings().one()
            self.assertEqual(row['mcp_enabled'], 1)
            self.assertEqual(row['mcp_apps_enabled'], 0)
            self.assertEqual(json.loads(row['mcp_tool_ids']), ['server:mcp:original'])
            connection.execute(text("UPDATE chat_widget SET mcp_apps_enabled=1, mcp_app_tool_ids='[\"bridge\"]'"))
            row = connection.execute(text('SELECT * FROM chat_widget')).mappings().one()
            self.assertEqual(json.loads(row['mcp_app_tool_ids']), ['bridge'])
            migration.downgrade()
            row = connection.execute(text('SELECT * FROM chat_widget')).mappings().one()
            self.assertEqual(row['mcp_enabled'], 1)
            self.assertNotIn('mcp_apps_enabled', row)
        engine.dispose()


class BridgeEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_selection_and_method_authorization(self):
        import ast
        import sys
        from unittest.mock import AsyncMock, patch
        from fastapi import APIRouter, Depends, HTTPException, Request
        from pydantic import BaseModel, ConfigDict, Field
        from sqlalchemy.ext.asyncio import AsyncSession
        from starlette.responses import Response
        from typing import Optional
        source = (path.parents[2] / 'routers/widgets.py').read_text()
        tree = ast.parse(source)
        tree.body = [node for node in tree.body if getattr(node, 'name', '') in {'WidgetAppCall', 'widget_bridge_call'}]
        widget = SimpleNamespace(id='widget', mcp_apps_enabled=True, mcp_app_tool_ids=['bridge'])
        owner = SimpleNamespace(model_dump=lambda: {'id': 'owner'})
        session = SimpleNamespace(id='session', chat_id='private-chat', ended_at=None, visitor_id='visitor', hidden_at=None)
        authorize = AsyncMock()
        module = SimpleNamespace(Valves=lambda **kw: kw, _handle_app_request=AsyncMock(return_value={'result': {}}))
        ns = dict(locals(), asyncio=asyncio, router=APIRouter(), get_async_session=lambda: None,
                  _ensure_public_request_size=lambda r: None, PUBLIC_WIDGET_REQUEST_BODY_LIMIT=10000,
                  _get_public_widget=AsyncMock(return_value=(widget, owner)),
                  _set_public_cors_headers=lambda *a: None, _set_owner_token=lambda *a: None,
                  ChatWidgetSessions=SimpleNamespace(get_session_by_id_and_widget_id=AsyncMock(return_value=session)),
                  is_hidden_past_grace=lambda value: False, _ensure_public_rate_limit=AsyncMock(),
                  _ensure_app_bridge_access=authorize)
        exec(compile(tree, '<widget endpoint>', 'exec'), ns)
        bridges._apps['capability'] = dict(session_id='session', tool_id='bridge', expires=float('inf'))
        body = dict(widget_id='widget', session_id='session', visitor_id='visitor',
                    app_id='capability', name='tools/call', arguments={'name': 'refresh'})
        request = SimpleNamespace(body=AsyncMock(side_effect=lambda: json.dumps(body).encode()), state=SimpleNamespace())
        mocks = {'open_webui.utils.mcp.widget_bridges': bridges,
                 'open_webui.utils.plugin': SimpleNamespace(get_tool_module_from_cache=AsyncMock(return_value=(module, None))),
                 'open_webui.models.tools': SimpleNamespace(Tools=SimpleNamespace(get_tool_valves_by_id=AsyncMock(return_value={}))) }
        async def call():
            return await ns['widget_bridge_call'](request, Response(), token=None, db=None)
        with patch.dict(sys.modules, mocks):
            self.assertEqual(await call(), {'result': {}})
            authorize.assert_awaited_once()
            for key, value, code in [('visitor_id', 'intruder', 403), ('app_id', 'unknown', 409), ('name', 'admin/delete', 400)]:
                previous = body[key]
                body[key] = value
                with self.assertRaises(HTTPException) as error:
                    await call()
                self.assertEqual(error.exception.status_code, code)
                body[key] = previous
            widget.mcp_apps_enabled = False
            with self.assertRaises(HTTPException) as error:
                await call()
            self.assertEqual(error.exception.status_code, 403)
            module._handle_app_request.assert_awaited_once()


class WrapperTests(unittest.IsolatedAsyncioTestCase):
    async def test_pipeline_rebinding_retains_bridge_adapter(self):
        import ast
        import inspect
        import sys
        from functools import partial, update_wrapper
        from typing import Callable, Awaitable, get_args, get_type_hints
        from unittest.mock import patch
        source = (path.parents[1] / 'tools.py').read_text()
        tree = ast.parse(source)
        tree.body = [node for node in tree.body if getattr(node, 'name', '') in
                     {'get_async_tool_function_and_apply_extra_params', 'get_updated_tool_function'}]
        ns = dict(locals())
        exec(compile(tree, '<tool bindings>', 'exec'), ns)
        received = []
        async def original(query: str, __user__: dict):
            received.append(__user__['id'])
            return HTMLResponse('var config = ' + json.dumps({'appHtml': '<h1>App</h1>'})), 'context'
        turn = SimpleNamespace(queue=asyncio.Queue(), allow_apps=True)
        request = SimpleNamespace(state=SimpleNamespace(widget_session_id='session'))
        wrapped = bridges.wrap_bridge(original, request, 'bridge', 'message')
        bound = await ns['get_async_tool_function_and_apply_extra_params'](wrapped, {'__user__': {'id': 'old'}})
        updated = await ns['get_updated_tool_function'](bound, {'__user__': {'id': 'new'}})
        with patch.dict(sys.modules, {'open_webui.utils.widget_stream': SimpleNamespace(get_widget_turn=lambda mid: turn)}):
            result = await updated(query='hello')
        self.assertEqual(received, ['new'])
        self.assertIn('displayed', result)
        self.assertIn('widget_bridge_app', turn.queue.get_nowait())


class EmittedBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_emitted_app_is_delivered_without_persisting_rpc_token(self):
        import sys
        from unittest.mock import AsyncMock, patch
        turn = SimpleNamespace(queue=asyncio.Queue(), allow_apps=True)
        request = SimpleNamespace(state=SimpleNamespace(widget_session_id='visitor'))
        emitter = AsyncMock()
        config = {'appHtml': '<h1>Sign in</h1>', 'rpc': {'token': 'OWNER_SECRET'}}
        async def open_odoo_sign_in(__event_emitter__):
            await __event_emitter__({'type': 'status', 'data': {'description': 'Preparing'}})
            await __event_emitter__({'type': 'embeds', 'data': {
                'embeds': ['<script>var config = ' + json.dumps(config) + ';</script>']}})
            return 'A private sign-in form has been sent to the chat.'
        call = bridges.wrap_bridge(open_odoo_sign_in, request, 'nirs', 'message')
        with patch.dict(sys.modules, {'open_webui.utils.widget_stream': SimpleNamespace(get_widget_turn=lambda mid: turn)}):
            text = await call(__event_emitter__=emitter)
        self.assertIn('displayed', text)
        event = turn.queue.get_nowait()
        self.assertEqual(event['widget_bridge_app']['html'], '<h1>Sign in</h1>')
        self.assertNotIn('OWNER_SECRET', str(event) + text + str(emitter.call_args_list))
        emitter.assert_awaited_once_with({'type': 'status', 'data': {'description': 'Preparing'}})

    async def test_scoped_and_unscoped_bridge_rpc(self):
        from unittest.mock import AsyncMock
        scopes = []
        async def scoped(method, params, request, user, tool_id, chat_id):
            scopes.append(chat_id)
            return {'result': {'authenticated': True}}
        module = SimpleNamespace(_handle_app_request=scoped)
        result = await bridges.call_bridge_app(module, 'tools/call', {}, None, {}, 'nirs', 'verified-chat')
        self.assertTrue(result['result']['authenticated'])
        self.assertEqual(scopes, ['verified-chat'])
        with self.assertRaises(ValueError):
            await bridges.call_bridge_app(module, 'tools/call', {}, None, {}, 'nirs', None)
        module._handle_app_request = AsyncMock(return_value={'result': {}})
        await bridges.call_bridge_app(module, 'tools/call', {}, None, {}, 'generic', 'verified-chat')
        module._handle_app_request.assert_awaited_once_with('tools/call', {}, None, {}, 'generic')


if __name__ == '__main__':
    unittest.main()
