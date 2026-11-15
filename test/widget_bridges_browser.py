"""Browser checks for the actual bundled MCP Apps host."""
import asyncio
import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]

class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args): pass

async def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel='msedge', headless=True)
            page = await browser.new_page()
            await page.goto(f'http://127.0.0.1:{server.server_port}/backend/open_webui/static/widget/defaults.json')
            await page.evaluate('document.body.innerHTML="<div id=app></div>"')
            await page.add_script_tag(url='/backend/open_webui/static/widget/markdown.js')
            await page.evaluate(r'''() => {
              window.calls=[];
              window.disposeApp=OpenWebUIWidgetMarkdown.mountApp(document.getElementById('app'), {
                bridge:true, toolInput:{arguments:{query:'hello'}}, toolResult:{content:[{type:'text',text:'result'}]},
                csp:{resourceDomains:["https://cdn.example.com/; script-src *", "javascript:alert(1)"]},
                html:`<button id="call">Run</button><div id="result"></div><script>
                  function send(method,params,id){parent.postMessage({jsonrpc:'2.0',method,params,id},'*')}
                  addEventListener('message',e=>{
                    if(e.data.id===1) send('ui/notifications/initialized',{});
                    if(e.data.method==='ui/notifications/tool-input') document.body.dataset.input=e.data.params.arguments.query;
                    if(e.data.method==='ui/notifications/tool-result') document.body.dataset.result=e.data.params.content[0].text;
                    if(e.data.id===2) document.getElementById('result').textContent=e.data.result.content[0].text;
                  });
                  document.getElementById('call').onclick=()=>send('tools/call',{name:'refresh',arguments:{}},2);
                  try{parent.document.body.dataset.compromised='yes'}catch{}
                  send('ui/initialize',{},1);
                <\/script>`
              }, async p=>{calls.push(p);return {result:{content:[{type:'text',text:'updated'}]}}});
            }''')
            frame = page.frame_locator('iframe')
            await frame.locator('body[data-input="hello"][data-result="result"]').wait_for()
            await frame.locator('#call').click()
            await frame.locator('#result').filter(has_text='updated').wait_for()
            assert await page.evaluate('calls.length') == 1
            assert await page.evaluate('document.body.dataset.compromised') is None
            assert await page.locator('iframe').get_attribute('sandbox') == 'allow-scripts allow-forms'
            assert 'https://cdn.example.com' not in (await page.locator('iframe').get_attribute('srcdoc'))
            # A sibling/parent cannot impersonate the opaque app frame.
            await page.evaluate("window.postMessage({jsonrpc:'2.0',method:'tools/call',params:{name:'evil'},id:3},'*')")
            await page.wait_for_timeout(100)
            assert await page.evaluate('calls.length') == 1
            await page.evaluate('disposeApp()')
            assert await page.locator('iframe').count() == 0
            await browser.close()
            print('PASS: MCP handshake, input/result, RPC, sandbox isolation, CSP filtering, sender validation and cleanup')
    finally:
        server.shutdown()

if __name__ == '__main__':
    asyncio.run(main())
