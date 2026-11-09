"""Knowledge metadata, source persistence and background lifecycle regressions."""
import ast
import asyncio
import logging
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]

def isolated(path, ns):
    tree = ast.parse((ROOT / path).read_text(encoding='utf8'))
    tree.body = [n for n in tree.body if not (isinstance(n, ast.ImportFrom) and (n.module or '').startswith('open_webui'))]
    exec(compile(tree, path, 'exec'), ns)
    return ns

class Item(SimpleNamespace):
    def model_copy(self, update):
        return Item(**(vars(self) | update))

class KnowledgeTests(unittest.IsolatedAsyncioTestCase):
    def setup_sync(self, selected=False):
        ns = {}
        isolated('backend/open_webui/utils/widget_crawl_urls.py', ns)
        isolated('backend/open_webui/utils/widget_knowledge_sync.py', ns)
        self.item = Item(id='crawl', kind='file', url='https://example.com/download?id=9', name='Prices for 2000 products.pdf',
            title=None, file_type='pdf', size=8000, found_on='https://example.com/catalog', found_on_title='Catalog',
            link_text='Price list', context='Wholesale prices', content_text=None, selected=selected, status='supported', http_status=200, depth=1)
        self.deleted = AsyncMock()
        self.fetch = AsyncMock()
        class Fetcher:
            def __init__(this, *args): pass
            async def __aenter__(this): return SimpleNamespace(fetch=self.fetch)
            async def __aexit__(this, *args): pass
        ns.update(CrawlFetcher=Fetcher, ensure_widget_knowledge=AsyncMock(return_value='knowledge'), remove_knowledge_file=self.deleted,
            ChatWidgetCrawlItems=SimpleNamespace(clear_extract_status=AsyncMock(), get_items_by_run_id=AsyncMock(return_value=[self.item]),set_extract_status=AsyncMock()),
            ChatWidgetKnowledgeItems=SimpleNamespace(get_items_by_widget_id=AsyncMock(return_value=[
                Item(id='old', kind='file',url=self.item.url,file_id='old-full-file'),
                Item(id='upload',kind='upload',url='local-upload',file_id='local-file')]), delete_item=AsyncMock()))
        sync=ns['KnowledgeSync'](None,Item(id='run',settings=Item(max_file_size_mb=20,max_total_size_mb=500,request_timeout=20)), Item(id='widget'),None,asyncio.Event())
        sync.save_progress=AsyncMock()
        self.documents=[]
        async def ingest(fetcher,knowledge,item,existing):
            if item.kind=='resource':
                _,_,body=await sync.build_document(fetcher,item)
                self.documents.append(body.decode())
            return 'embedded',None
        sync.sync_item=ingest
        return sync,ns

    async def test_excluded_file_has_searchable_metadata_without_download(self):
        sync,ns=self.setup_sync()
        await sync.run_sync()
        self.fetch.assert_not_awaited()
        self.deleted.assert_awaited_once_with('knowledge','old-full-file')
        text=self.documents[0]
        for value in ['Prices for 2000 products.pdf','https://example.com/download?id=9','https://example.com/catalog','Catalog','Wholesale prices','excluded by owner']:
            self.assertIn(value,text)
        ns['ChatWidgetCrawlItems'].set_extract_status.assert_awaited_once_with('crawl','metadata_only',None)

    async def test_selected_file_keeps_metadata_and_content_status(self):
        sync,ns=self.setup_sync(selected=True)
        await sync.run_sync()
        self.deleted.assert_not_awaited()
        self.assertIn('indexed separately', self.documents[0])
        ns['ChatWidgetCrawlItems'].set_extract_status.assert_awaited_once_with('crawl','embedded',None)

class SourceTests(unittest.TestCase):
    def setUp(self):
        self.ns=isolated('backend/open_webui/utils/widget_stream.py', {'get_output_text': lambda output: output or ''})
        self.turn=self.ns['WidgetTurn']('message')
    def test_source_links_are_in_final_stream_and_persisted_content(self):
        self.turn.handle_event({'type':'source','data':{'source':{'name':'Product'},'metadata':[{'source_url':'https://example.com/product?id=9'}]}})
        self.turn.handle_event({'type':'chat:completion','data':{'done':True,'output':'The price is 25.'}})
        self.assertIn('[Product](<https://example.com/product?id=9>)',self.turn.content)
        self.assertEqual(self.turn.queue.get_nowait()['widget_final']['content'],self.turn.content)
    def test_no_fabricated_links_and_unsafe_urls_rejected(self):
        self.turn.add_source({'source':{'url':'javascript:alert(1)'}})
        self.turn.final_text='Answer without a source.'
        self.assertEqual(self.turn.content,'Answer without a source.')
    def test_existing_links_not_repeated_and_late_source_emitted(self):
        self.turn.final_text='[Product](https://example.com/p)'
        self.turn.handle_event({'type':'source','data':{'source':{'name':'Product','url':'https://example.com/p'}}})
        self.assertNotIn('Source links',self.turn.content)
        self.assertEqual(self.turn.queue.get_nowait()['widget_final']['content'],self.turn.content)

class BackgroundTests(unittest.IsolatedAsyncioTestCase):
    async def test_job_outlives_request_and_still_cancellable(self):
        ns=isolated('backend/open_webui/utils/widget_crawl_jobs.py', {'ChatWidgetCrawlRuns':SimpleNamespace(touch_heartbeat=AsyncMock()),'HEARTBEAT_INTERVAL_SECONDS':30})
        started=asyncio.Event()
        async def runner(cancel):
            started.set()
            await cancel.wait()
        async def request():
            return ns['start_job']('widget','run','crawl',runner)
        job=await request()
        await started.wait()
        self.assertFalse(job.task.done())
        ns['request_cancel']('widget')
        await job.task
        self.assertNotIn('widget',ns['_jobs'])

if __name__=='__main__':unittest.main()
