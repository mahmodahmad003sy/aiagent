"""Step-by-step check of how the widget crawler sees one URL.

Usage (from the backend folder, same Python/venv that runs Open WebUI):
    python diagnose_crawl.py https://delmedprom-mcp.smartlilac.com/
"""

import asyncio
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
os.environ.setdefault('WEBUI_SECRET_KEY', 'diagnose')
os.environ.setdefault('DATA_DIR', tempfile.mkdtemp())


def step(title):
    print(f'\n=== {title} ===', flush=True)


async def main(url):
    from open_webui.utils.widget_crawl_fetch import CrawlFetcher
    from open_webui.utils.widget_crawl_render import CrawlRenderer, needs_rendering
    from open_webui.utils.widget_crawler import decode_html, parse_html_page

    step('1. Plain HTTP fetch (what the crawler downloads)')
    async with CrawlFetcher(20) as fetcher:
        result = await fetcher.fetch(url)
    print('status:', result.status, '| http:', result.http_status, '| final url:', result.url)
    print('content-type:', result.content_type, '| bytes:', len(result.body))
    if result.status != 'ok':
        print('-> The crawler cannot even download the page. Stop here.')
        return
    html = decode_html(result.body, result.content_type)
    print('first 600 chars of HTML:\n', html[:600])

    step('2. Text found in plain HTML')
    page = parse_html_page(html, result.url)
    print('title:', page.title, '| canonical:', page.canonical, '| links:', len(page.links))
    print('text length:', len(page.text), '| text:', repr(page.text[:300]))

    step('3. Rendering decision')
    decision = needs_rendering('auto', html, page.text)
    print('needs JavaScript rendering (auto):', decision)

    step('4. Headless browser render')
    async with CrawlRenderer(30) as renderer:
        rendered = await renderer.render(url)
        print('browser engine:', renderer.engine, '| available:', renderer.available, '| error:', renderer.error)
        print('render status:', rendered.status, '| http:', rendered.http_status, '| error:', rendered.error)
        print('browser bytes downloaded:', renderer.bytes_downloaded)
    if rendered.status == 'ok':
        rpage = parse_html_page(rendered.html, url)
        print('rendered title:', rpage.title, '| links:', len(rpage.links))
        print('rendered text length:', len(rpage.text))
        print('rendered text:', repr(rpage.text[:600]))
        print('rendered links:', [link.url for link in rpage.links][:20])
        if len(rpage.text) < 30:
            print('rendered HTML (first 1500 chars):\n', rendered.html[:1500])


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else 'https://delmedprom-mcp.smartlilac.com/'))
