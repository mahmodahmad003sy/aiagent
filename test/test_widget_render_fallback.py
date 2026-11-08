import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

class FetchPageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        path=Path(__file__).resolve().parents[1]/'backend/open_webui/utils/widget_crawler.py'
        tree=ast.parse(path.read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='WidgetCrawler')
        method=next(n for n in cls.body if getattr(n,'name','')=='fetch_page')
        ns={'FetchResult':lambda **kw:SimpleNamespace(**kw),'MAX_PAGE_BYTES':10000}
        method.returns=None
        exec(compile(ast.Module(body=[method],type_ignores=[]),'fetch','exec'),ns)
        self.fetch=ns['fetch_page']
        self.crawler=SimpleNamespace(settings=SimpleNamespace(crawl_provider='standard',render_js='always'),
            fetcher=SimpleNamespace(fetch=AsyncMock(return_value=SimpleNamespace(status='timeout')),_pace=AsyncMock()),
            renderer=SimpleNamespace(render=AsyncMock(return_value=SimpleNamespace(url='https://example.com',status='ok',http_status=200,html='<h1>Content</h1>',bytes_downloaded=20,error=None))),
            bytes_downloaded=0,check_cancel=lambda:None)
    async def test_always_skips_preliminary_fetch(self):
        result,rendered=await self.fetch(self.crawler,'https://example.com')
        self.assertEqual(result.status,'ok');self.assertTrue(rendered)
        self.crawler.fetcher.fetch.assert_not_awaited()
    async def test_auto_falls_back_on_timeout(self):
        self.crawler.settings.render_js='auto'
        result,rendered=await self.fetch(self.crawler,'https://example.com')
        self.assertTrue(rendered);self.assertEqual(result.status,'ok')
    async def test_never_and_security_errors_do_not_fall_back(self):
        for mode,status in [('never','timeout'),('auto','blocked'),('auto','http_error')]:
            self.crawler.settings.render_js=mode
            self.crawler.fetcher.fetch.return_value=SimpleNamespace(status=status)
            result,rendered=await self.fetch(self.crawler,'https://example.com')
            self.assertFalse(rendered);self.assertEqual(result.status,status)
        self.crawler.renderer.render.assert_not_awaited()

if __name__=='__main__':unittest.main()
