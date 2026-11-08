import ast
import asyncio
import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import aiohttp
import markdown

ROOT = Path(__file__).resolve().parents[1]

class Reply:
    def __init__(self, status, data):
        self.status = status
        self.data = data
        self.content = self
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def iter_chunked(self, size): yield json.dumps(self.data).encode()

class VipTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tree = ast.parse((ROOT/'backend/open_webui/utils/widget_crawl_vip.py').read_text(encoding='utf-8'))
        tree.body = [n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.Assign))]
        from urllib.parse import quote, urlparse
        def result(url, status, **kw): return SimpleNamespace(url=url,status=status,**kw)
        self.ns = dict(asyncio=asyncio,json=json,os=os,aiohttp=aiohttp,markdown=markdown,quote=quote,urlparse=urlparse,validate_url=lambda url: None,FetchResult=result)
        exec(compile(tree,'vip','exec'),self.ns)
    def test_epc_wait_selector_matches_request_script(self):
        pick = self.ns['vip_wait_selector']
        self.assertEqual(pick('https://epc.ae/en/home', ''), 'a[href*="/en/details/"]')
        self.assertEqual(pick('https://www.epc.ae/', ''), 'a[href*="/en/details/"]')
        self.assertEqual(pick('https://epc.ae/en/other', ''), '')
        self.assertEqual(pick('https://epc.ae/en/home', '.article'), '.article')

    def test_markdown_links_and_error_pages(self):
        f=self.ns['decode_page']
        result=f('https://example.com',dict(http_code=200,status='success',body='# Article\n[More](/news)'),10000)
        self.assertEqual(result.status,'ok')
        self.assertIn(b'href="/news"',result.body)
        for body in ('', 'Please solve this CAPTCHA'):
            self.assertNotEqual(f('https://example.com',dict(http_code=200,body=body),10000).status,'ok')
        self.assertNotEqual(f('https://example.com',dict(http_code=200,status='warn',body='partial'),10000).status,'ok')
    async def test_408_polls_without_second_post(self):
        replies=[Reply(202,{}),Reply(200,dict(status='success',http_code=200,body='# Loaded'))]
        class Session:
            posts=0
            last_payload=None
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            def post(self,*args,**kwargs):
                self.posts+=1
                self.last_payload=kwargs.get('json')
                return Reply(408,dict(response_id='test-id'))
            def get(self,*args,**kwargs): return replies.pop(0)
        session=Session()
        async def sleep(_): pass
        with patch.dict(os.environ,{'SCRAPER_API_KEY':'test'}), patch.object(aiohttp,'ClientSession',return_value=session), patch.object(asyncio,'sleep',sleep):
            result=await self.ns['fetch_vip']('https://example.com','',10000,lambda:None)
        self.assertEqual(result.status,'ok')
        self.assertEqual(session.posts,1)
        self.assertFalse(replies)

    async def test_epc_home_posts_wait_for_selector(self):
        replies=[Reply(200,dict(status='success',http_code=200,body='# EPC\n[Article](/en/details/1)'))]
        class Session:
            last_payload=None
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            def post(self,*args,**kwargs):
                self.last_payload=kwargs.get('json')
                return replies[0]
            def get(self,*args,**kwargs): raise AssertionError('unexpected poll')
        session=Session()
        with patch.dict(os.environ,{'SCRAPER_API_KEY':'test'}), patch.object(aiohttp,'ClientSession',return_value=session):
            result=await self.ns['fetch_vip']('https://epc.ae/en/home','',10000,lambda:None)
        self.assertEqual(result.status,'ok')
        wait_for=session.last_payload.get('waitFor') or {}
        self.assertEqual(wait_for.get('element'), 'a[href*="/en/details/"]')
        self.assertTrue(wait_for.get('checkVisible'))

if __name__=='__main__': unittest.main()
