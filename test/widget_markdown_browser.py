"""Browser regression for the standalone widget and bundled Markdown renderer."""
import asyncio
import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parents[1]
class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self,*args): pass

async def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(QuietHandler,directory=str(ROOT)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    base=f'http://127.0.0.1:{server.server_port}'
    answer='''| ID | Project | Manager | Tasks | Description |
| --- | --- | --- | --- | --- |
| 4 | **Smart Lilac AI Studio** | Administrator | 3 | AI studio with a wide description |
| 2 | **Student Task Management** | Administrator | 2 | Central project for tracking tasks |

1. First result
2. Second result

**Worth noting:** File contents were not indexed.

[Download price list](https://example.com/prices.pdf)

<script>window.widgetXss=1</script><img src=x onerror="window.widgetXss=2">
[Unsafe](javascript:alert(1))'''
    try:
        async with async_playwright() as p:
            browser=await p.chromium.launch(channel='msedge',headless=True)
            page=await browser.new_page(viewport={'width':1100,'height':850})
            async def api(route):
                if '/public/config' in route.request.url:
                    await route.fulfill(json={'name':'Knowledge assistant','welcome_message':answer,'theme':{'feedback_enabled':True}})
                elif '/public/chat' in route.request.url:
                    if route.request.post_data_json.get('message') == 'Stream':
                        events=[{'choices':[{'delta':{'content':answer[:40]}}]}, {'widget_final':{'content':answer}}]
                        await route.fulfill(content_type='text/event-stream',body=''.join('data: '+json.dumps(event)+'\n\n' for event in events)+'data: [DONE]\n\n')
                        return
                    await route.fulfill(json={'content':answer,'session_id':'test','assistant_message_id':'answer','created_at':1,'assistant_created_at':2})
                else: await route.fulfill(json={})
            await page.route('**/api/v1/widgets/**',api)
            await page.goto(base+'/backend/open_webui/static/widget/defaults.json')
            await page.evaluate('document.body.innerHTML=""')
            await page.evaluate('''url=>{let s=document.createElement('script');s.src=url;s.dataset.widgetId='markdown-test';s.dataset.token='test';document.body.appendChild(s)}''',base+'/backend/open_webui/static/widget/chat-widget.js')
            await page.locator('.owui-launcher').click()
            await page.wait_for_selector('.owui-markdown table')
            assert await page.locator('.owui-markdown table tbody tr').count()==2
            assert await page.locator('.owui-markdown ol li').count()==2
            assert await page.locator('.owui-markdown strong').count()==3
            assert await page.locator('.owui-markdown script,.owui-markdown img').count()==0
            assert await page.evaluate('window.widgetXss') is None
            assert await page.locator('.owui-markdown a[href^="javascript:"]').count()==0
            assert await page.locator('a[href="https://example.com/prices.pdf"]').get_attribute('rel')=='noopener noreferrer'
            await page.screenshot(path=str(ROOT/'tasks/widget-markdown-desktop.png'))
            await page.set_viewport_size({'width':390,'height':844})
            await page.screenshot(path=str(ROOT/'tasks/widget-markdown-mobile.png'))
            overflow=await page.locator('.owui-table-scroll').evaluate('(e)=>({scroll:e.scrollWidth,client:e.clientWidth})')
            assert overflow['scroll']>overflow['client']
            await page.locator('.owui-input').fill('Show the results')
            await page.locator('.owui-send').click()
            await page.wait_for_function('document.querySelectorAll(".owui-markdown table").length===2')
            await page.wait_for_function('!document.querySelector(".owui-send").disabled')
            await page.locator('.owui-input').fill('Stream')
            await page.locator('.owui-send').click()
            await page.wait_for_function('document.querySelectorAll(".owui-markdown table").length===3')
            await browser.close()
            print('PASS: widget tables, lists, emphasis, safe links, malicious HTML rejection, mobile table scrolling, JSON and streamed answers')
    finally:server.shutdown()

if __name__=='__main__':asyncio.run(main())
