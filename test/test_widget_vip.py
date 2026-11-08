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
        from urllib.parse import quote
        def result(url, status, **kw): return SimpleNamespace(url=url,status=status,**kw)
        self.ns = dict(asyncio=asyncio,json=json,os=os,aiohttp=aiohttp,markdown=markdown,quote=quote,validate_url=lambda url: None,FetchResult=result)
        exec(compile(tree,'vip','exec'),self.ns)
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
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            def post(self,*args,**kwargs):
                self.posts+=1
                return Reply(408,dict(response_id='test-id'))
            def get(self,*args,**kwargs): return replies.pop(0)
        session=Session()
        async def sleep(_): pass
        with patch.dict(os.environ,{'SCRAPER_API_KEY':'test'}), patch.object(aiohttp,'ClientSession',return_value=session), patch.object(asyncio,'sleep',sleep):
            result=await self.ns['fetch_vip']('https://example.com','',10000,lambda:None)
        self.assertEqual(result.status,'ok')
        self.assertEqual(session.posts,1)
        self.assertFalse(replies)

if __name__=='__main__': unittest.main()
