"""End-to-end widget SSE regression for separately emitted app embeds."""
import asyncio
import functools
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from playwright.async_api import async_playwright
from widget_bridges_browser import ROOT, QuietHandler
from test_widget_bridges import bridges
from test_widget_assets import asset_client
from urllib.parse import urlsplit

APP = '''<button id="login">Sign in and continue</button><div id="result"></div><script>
function send(method,params,id){parent.postMessage({jsonrpc:'2.0',method,params,id},'*')}
addEventListener('message',e=>{
 if(e.data.id===1)send('ui/notifications/initialized',{});
 if(e.data.id===2)document.getElementById('result').textContent=e.data.result.structuredContent.authenticated?'Signed in':'Failed';
});
document.getElementById('login').onclick=()=>send('tools/call',{name:'odoo_login',arguments:{password:'TEST_PASSWORD'}},2);
send('ui/initialize',{},1);
</script>'''

async def main():
    turn = SimpleNamespace(queue=asyncio.Queue(), allow_apps=True)
    request = SimpleNamespace(state=SimpleNamespace(widget_session_id='visitor-session'))
    async def emitted(__event_emitter__):
        config = {'appHtml': APP, 'rpc': {'token': 'PRIVATE_RPC_TOKEN'}}
        await __event_emitter__({'type': 'embeds', 'data': {'embeds': ['var config = ' + json.dumps(config)]}})
        return 'Sign-in form sent'
    with patch.dict(sys.modules, {'open_webui.utils.widget_stream': SimpleNamespace(get_widget_turn=lambda mid: turn)}):
        await bridges.wrap_bridge(emitted, request, 'nirs', 'message')(__event_emitter__=AsyncMock())
    app_event = turn.queue.get_nowait()
    assert 'PRIVATE_RPC_TOKEN' not in json.dumps(app_event)
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    calls = []
    asset_requests = []
    assets = asset_client()
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel='msedge', headless=True)
            page = await browser.new_page()
            async def api(route):
                if urlsplit(route.request.url).path.endswith(('/public/embed.js', '/public/markdown.js')):
                    asset_path = urlsplit(route.request.url).path
                    response = assets.get(asset_path)
                    assert response.status_code == 200, asset_path
                    asset_requests.append(asset_path)
                    await route.fulfill(status=response.status_code, headers=dict(response.headers), body=response.content)
                elif '/public/config' in route.request.url:
                    await route.fulfill(json={'name':'Odoo', 'welcome_message':'Hello', 'theme':{}})
                elif '/public/chat' in route.request.url:
                    events = [{'widget': {'session_id':'visitor-session'}}, app_event,
                              {'widget_final': {'content':'Use the private form to sign in.'}}]
                    await route.fulfill(content_type='text/event-stream', body=''.join('data: '+json.dumps(e)+'\n\n' for e in events)+'data: [DONE]\n\n')
                elif '/public/bridge/call' in route.request.url:
                    body = route.request.post_data_json
                    assert body['session_id'] == 'visitor-session'
                    assert body['app_id'] == app_event['widget_bridge_app']['id']
                    assert body['name'] == 'tools/call'
                    calls.append(body)
                    await route.fulfill(json={'result':{'content':[], 'structuredContent':{'authenticated':True}}})
                else:
                    await route.fulfill(json={})
            await page.route('**/api/v1/widgets/**', api)
            await page.goto(base+'/backend/open_webui/static/widget/defaults.json')
            await page.evaluate('document.body.innerHTML=""')
            await page.evaluate('''url=>{const s=document.createElement('script');s.src=url;s.dataset.widgetId='test-widget';s.dataset.token='test-token';document.body.appendChild(s)}''',base+'/api/v1/widgets/public/embed.js')
            await page.locator('.owui-launcher').click()
            await page.locator('.owui-input').fill('sign')
            await page.locator('.owui-send').click()
            await page.wait_for_function('!document.querySelector(".owui-send").disabled')
            frame = page.frame_locator('.owui-private-app iframe')
            await frame.locator('#login').click()
            await frame.locator('#result').filter(has_text='Signed in').wait_for()
            assert len(calls) == 1
            assert asset_requests == ['/api/v1/widgets/public/embed.js', '/api/v1/widgets/public/markdown.js']
            assert 'TEST_PASSWORD' not in await page.locator('.owui-messages').inner_text()
            assert await page.locator('.owui-private-app iframe').count() == 1
            await page.locator('.owui-new-chat').click()
            await page.wait_for_function('document.querySelectorAll(".owui-private-app iframe").length===0')
            await browser.close()
            print('PASS: emitted embed reaches widget, survives final answer, invokes scoped RPC and clears on new chat')
    finally:
        assets.close()
        server.shutdown()

if __name__ == '__main__':
    asyncio.run(main())
