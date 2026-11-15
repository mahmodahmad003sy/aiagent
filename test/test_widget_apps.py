"""Private app queue tests without initializing the application's database."""
import asyncio
import importlib.util
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

path = Path(__file__).resolve().parents[1] / 'backend/open_webui/utils/mcp/widget_apps.py'
spec = importlib.util.spec_from_file_location('widget_apps_tested', path)
apps = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = apps
spec.loader.exec_module(apps)


class WidgetAppTests(unittest.IsolatedAsyncioTestCase):
    def make_client(self):
        return SimpleNamespace(app_tools={'odoo_login': {'resourceUri': 'ui://login', 'visibility': ['app']}},
            read_resource=AsyncMock(return_value={'contents': [{'mimeType': 'text/html;profile=mcp-app', 'text': '<html>Login</html>'}]}),
            session=SimpleNamespace(call_tool=AsyncMock(return_value=SimpleNamespace(model_dump=lambda **kw:
                {'content': [], 'structuredContent': {'authenticated': True}}))))

    async def test_private_login_resumes_without_exposing_credentials(self):
        client, turn = self.make_client(), SimpleNamespace(queue=asyncio.Queue())
        task = asyncio.create_task(apps.authenticate(client, turn, 'visitor-a', 'ui://login'))
        event = await turn.queue.get()
        app_id = event['widget_app']['id']
        with self.assertRaises(ValueError):
            await apps.submit(app_id, 'visitor-b', 'odoo_login', {})
        with self.assertRaises(ValueError):
            await apps.submit(app_id, 'visitor-a', 'delete_project', {})
        arguments = {'username': 'alice', 'password': 'secret'}
        response = await apps.submit(app_id, 'visitor-a', 'odoo_login', arguments)
        self.assertTrue(response['structuredContent']['authenticated'])
        self.assertTrue(await task)
        self.assertEqual(arguments, {})
        self.assertNotIn(app_id, apps._apps)
        self.assertNotIn('secret', str(event) + str(await turn.queue.get()))
        self.assertEqual(client.session.call_tool.await_count, 1)

    async def test_cancel_closes_form_without_login(self):
        client, turn = self.make_client(), SimpleNamespace(queue=asyncio.Queue())
        task = asyncio.create_task(apps.authenticate(client, turn, 'visitor', 'ui://login'))
        event = await turn.queue.get()
        apps.cancel_session('visitor')
        self.assertFalse(await task)
        self.assertFalse(apps._apps)
        client.session.call_tool.assert_not_called()

    async def test_timeout_closes_form(self):
        client, turn = self.make_client(), SimpleNamespace(queue=asyncio.Queue())
        old = apps.APP_TIMEOUT
        apps.APP_TIMEOUT = .01
        try:
            self.assertFalse(await apps.authenticate(client, turn, 'visitor', 'ui://login'))
            self.assertFalse(apps._apps)
        finally:
            apps.APP_TIMEOUT = old

    async def test_cancel_during_login_prevents_continuation(self):
        client, turn = self.make_client(), SimpleNamespace(queue=asyncio.Queue())
        started, release = asyncio.Event(), asyncio.Event()
        async def slow_login(*args):
            started.set()
            await release.wait()
            return SimpleNamespace(model_dump=lambda **kw: {'content': [], 'structuredContent': {'authenticated': True}})
        client.session.call_tool.side_effect = slow_login
        task = asyncio.create_task(apps.authenticate(client, turn, 'visitor', 'ui://login'))
        event = await turn.queue.get()
        app_id = event['widget_app']['id']
        login = asyncio.create_task(apps.submit(app_id, 'visitor', 'odoo_login', {'password': 'secret'}))
        await started.wait()
        self.assertTrue((await apps.submit(app_id, 'visitor', '__cancel__', {}))['cancelled'])
        release.set()
        await login
        self.assertFalse(await task)

    async def test_failed_password_keeps_form_open(self):
        client, turn = self.make_client(), SimpleNamespace(queue=asyncio.Queue())
        client.session.call_tool.return_value = SimpleNamespace(model_dump=lambda **kw: {'content': [], 'structuredContent': {'authenticated': False}})
        task = asyncio.create_task(apps.authenticate(client, turn, 'visitor', 'ui://login'))
        event = await turn.queue.get()
        await apps.submit(event['widget_app']['id'], 'visitor', 'odoo_login', {'password': 'bad'})
        self.assertFalse(task.done())
        apps.cancel_session('visitor')
        self.assertFalse(await task)


if __name__ == '__main__':
    unittest.main()
