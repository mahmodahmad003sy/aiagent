"""Exercise the actual bundled React form inside the widget's sandbox host."""
import asyncio
import os
import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]

class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args): pass

async def main(bridge=False):
    html = Path(os.environ.get('WIDGET_SIGN_IN_HTML', r'D:\odoo_18_mcpNirs\dist\sign-in.html')).read_text(encoding='utf-8')
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel='msedge', headless=True)
            page = await browser.new_page(viewport={'width': 400, 'height': 700})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto(f'http://127.0.0.1:{server.server_port}/backend/open_webui/static/widget/defaults.json')
            await page.evaluate('document.body.innerHTML="<div id=app></div>"')
            await page.add_script_tag(url='/backend/open_webui/static/widget/markdown.js')
            await page.evaluate('''input => {
              window.calls=[];
              window.disposeApp=OpenWebUIWidgetMarkdown.mountApp(document.getElementById('app'),{html:input.html,bridge:input.bridge},async p=>{
                if(input.bridge) p=p.arguments;
                calls.push(p.name);
                const result = {content:[],structuredContent:p.name==='odoo_login' ?
                  {authenticated:p.arguments.password==='correct',message:'Check your sign-in details.'} : {authenticated:false}};
                return input.bridge ? {result} : result;
              });
            }''', {'html': html, 'bridge': bridge})
            frame = page.frame_locator('iframe')
            await frame.get_by_label('Username or email').fill('alice@example.com')
            await frame.get_by_label('Password', exact=True).fill('wrong')
            await frame.get_by_role('button', name='Sign in and continue').click()
            await frame.get_by_role('alert').wait_for(timeout=5000)
            assert await frame.get_by_label('Password', exact=True).input_value() == ''
            await page.screenshot(path=str(ROOT / 'tasks/odoo-sign-in-mobile.png'))
            await frame.get_by_label('Password', exact=True).fill('correct')
            await frame.get_by_role('button', name='Show password').click()
            assert await frame.get_by_label('Password', exact=True).get_attribute('type') == 'text'
            await frame.get_by_role('button', name='Sign in and continue').click()
            await frame.get_by_role('heading', name='You’re signed in').wait_for()
            assert await page.evaluate('calls') == ['odoo_auth_status', 'odoo_login', 'odoo_login']
            assert await page.locator('iframe').get_attribute('sandbox') == 'allow-scripts allow-forms'
            assert await page.evaluate("document.body.textContent.includes('correct')") is False
            assert not errors, errors
            await page.evaluate('disposeApp()')
            assert await page.locator('iframe').count() == 0
            await browser.close()
            print(('BRIDGE: ' if bridge else 'NATIVE: ') + 'PASS: real React app handshake, invalid login, password clearing, reveal, successful login, isolated iframe, cleanup')
    finally:
        server.shutdown()

if __name__ == '__main__':
    asyncio.run(main())
    asyncio.run(main(bridge=True))
