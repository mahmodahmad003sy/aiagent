"""Isolated regression tests; never initialize the application's real database."""
import ast
import asyncio
import io
import unittest
from pathlib import Path, PurePath
from types import SimpleNamespace
from typing import Literal, Optional
from unittest.mock import AsyncMock
from urllib.parse import urlparse, urlsplit

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.responses import FileResponse

ROOT = Path(__file__).resolve().parents[1]


def load(path, names, ns):
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    tree.body = [ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)] + [
        node for node in tree.body if getattr(node, 'name', '') in names]
    exec(compile(ast.fix_missing_locations(tree), str(ROOT / path), 'exec'), ns)


class SourcesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ns = dict(globals(), __file__=str(ROOT / 'backend/open_webui/routers/widgets.py'),
                       router=APIRouter(), get_verified_user=lambda: None, get_async_session=lambda: None,
                       ERROR_MESSAGES=SimpleNamespace(ACCESS_PROHIBITED='Forbidden', NOT_FOUND='Not found'))
        exec((ROOT / 'backend/open_webui/utils/widget_crawl_urls.py').read_text(encoding='utf-8'), self.ns)
        self.ns.update(CrawlFileType=Literal['pdf', 'docx', 'xlsx', 'csv', 'txt', 'pptx'],
                       CrawlRenderMode=Literal['auto', 'always', 'never'])
        load('backend/open_webui/models/chat_widget_crawl.py', {'_normalize_paths', 'ChatWidgetCrawlSettings'}, self.ns)
        self.ns['ChatWidgetCrawlSettings'].model_rebuild(_types_namespace=self.ns)

    def test_extra_urls_normalize_and_validate(self):
        settings = self.ns['ChatWidgetCrawlSettings'](start_url='https://main.example',
            extra_urls=['https://other.example/a#part', 'https://other.example/a'])
        self.assertEqual(settings.extra_urls, ['https://other.example/a'])
        for urls in [['file:///secret'], ['https://other.example/' + str(i) for i in range(51)]]:
            with self.assertRaises(ValidationError):
                self.ns['ChatWidgetCrawlSettings'](start_url='https://main.example', extra_urls=urls)

    async def test_explicit_external_page_does_not_follow_links(self):
        load('backend/open_webui/utils/widget_crawler.py', {'new_item', 'WidgetCrawler'}, self.ns)
        settings = self.ns['ChatWidgetCrawlSettings'](start_url='https://main.example',
            extra_urls=['https://other.example/page'], respect_robots=False)
        crawler = self.ns['WidgetCrawler']('run', settings, asyncio.Event())
        page = SimpleNamespace(title='Extra page', text='A useful external page with sufficient text.', canonical=None,
            links=[SimpleNamespace(url='https://other.example/unwanted', text='', context='')])
        self.ns.update(decode_html=lambda *args: '', parse_html_page=lambda *args: page)
        crawler.render_if_needed = AsyncMock(return_value=page)
        crawler.fetcher = SimpleNamespace(fetch=AsyncMock(return_value=SimpleNamespace(
            url='https://other.example/page', status='ok', body=b'<html>Text</html>', content_type='text/html',
            http_status=200, content_length=20)))
        links, fetched = await crawler.crawl_page(('https://other.example/page', None, None), 0)
        self.assertTrue(fetched)
        self.assertEqual(links, [])
        self.assertEqual(crawler.items['https://other.example/page']['status'], 'ok')
        self.assertIsNone(crawler.handle_link('https://unlisted.example/page', 1, '', '', '', ''))

    def test_hosted_preview_and_external_domain_rules(self):
        load('backend/open_webui/routers/widgets.py', {'_domain_from_value', '_request_domain', '_domain_matches', '_ensure_domain_allowed'}, self.ns)
        widget = SimpleNamespace(allowed_domains=['customer.example'])
        def request(source):
            return Request({'type': 'http', 'scheme': 'http', 'server': ('localhost', 5173),
                            'path': '/api/v1/widgets/public/config', 'headers': [(b'referer', source.encode())]})
        self.ns['_ensure_domain_allowed'](request('http://localhost:5173/preview/example'), widget)
        self.ns['_ensure_domain_allowed'](request('https://customer.example/page'), widget)
        with self.assertRaises(HTTPException):
            self.ns['_ensure_domain_allowed'](request('https://unlisted.example/page'), widget)

    async def test_upload_uses_existing_ingestion_and_stays_outside_crawl_manifest(self):
        widget = SimpleNamespace(id='widget', user_id='owner', knowledge_id='knowledge')
        ingest = AsyncMock(return_value=('file-id', 'embedded', None))
        self.ns.update(LOCAL_UPLOAD_LIMIT=20 * 1024 * 1024, JOB_ALREADY_RUNNING='Busy',
            _get_owned_widget=AsyncMock(return_value=widget), Users=SimpleNamespace(get_user_by_id=AsyncMock(return_value=object())),
            ChatWidgets=SimpleNamespace(get_widget_by_id=AsyncMock(return_value=widget)),
            ChatWidgetCrawlRuns=SimpleNamespace(get_active_run=AsyncMock(return_value=None)),
            ensure_widget_knowledge=AsyncMock(return_value='knowledge'), add_document_to_knowledge=ingest,
            job_start_lock=asyncio.Lock())
        # Omit route decorators for isolated direct endpoint invocation.
        tree = ast.parse((ROOT / 'backend/open_webui/routers/widget_crawl.py').read_text(encoding='utf-8'))
        tree.body = [node for node in tree.body if getattr(node, 'name', '') == 'upload_widget_knowledge']
        tree.body[0].decorator_list = []
        tree.body.insert(0, ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0))
        exec(compile(ast.fix_missing_locations(tree), 'upload', 'exec'), self.ns)
        upload = UploadFile(filename='notes.txt', file=io.BytesIO(b'Knowledge text'))
        result = await self.ns['upload_widget_knowledge'](None, 'widget', upload, user=None, db=None)
        self.assertEqual(result['id'], 'file-id')
        self.assertEqual(ingest.call_args.args[4].kind, 'upload')
        self.assertEqual(ingest.call_args.args[-1], b'Knowledge text')
        self.assertTrue(upload.file.closed)
        with self.assertRaises(HTTPException):
            await self.ns['upload_widget_knowledge'](None, 'widget', UploadFile(filename='bad.exe', file=io.BytesIO(b'bad')), user=None, db=None)


if __name__ == '__main__':
    unittest.main()
