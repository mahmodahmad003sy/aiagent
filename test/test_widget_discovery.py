"""Crawler discovery regressions without application/database startup."""
import ast
import json
import re
import sys
import types
import unittest
from pathlib import Path

from test_widget_next_data import production_parser, payload

ROOT = Path(__file__).resolve().parents[1]
UTILS = ROOT / 'backend/open_webui/utils'
urls = types.ModuleType('open_webui.utils.widget_crawl_urls')
exec((UTILS / 'widget_crawl_urls.py').read_text(encoding='utf8'), urls.__dict__)
sys.modules[urls.__name__] = urls
ns = {}
exec((UTILS / 'widget_crawl_discovery.py').read_text(encoding='utf8'), ns)
tree = ast.parse((UTILS / 'widget_crawl_render.py').read_text(encoding='utf8'))
render_ns = {'re': re, 'MIN_PAGE_TEXT_CHARS': 30,
             '_APP_ROOT_RE': re.compile(r'<div id="root"></div>'),
             '_MODULE_SCRIPT_RE': re.compile(r'<script type="module"')}
exec(compile(ast.Module(body=[n for n in tree.body if getattr(n, 'name', '') == 'needs_rendering'], type_ignores=[]), 'render', 'exec'), render_ns)

class DiscoveryTests(unittest.TestCase):
    def test_service_cards_keep_distinct_query_ids_with_visible_text(self):
        html = '<main>' + 'Visible text ' * 10 + '</main>' + payload({'sectionsContent': {'services': {
            'items': [{'id': 43, 'title': 'ISS'}, {'id': 42, 'title': 'Apps'}]}}})
        page = production_parser()(html, 'https://metasolutions.ae/')
        self.assertEqual({l.url for l in page.links}, {'https://metasolutions.ae/services/subservices?id=43', 'https://metasolutions.ae/services/subservices?id=42'})

    def test_auto_renders_hydration_text_without_navigation(self):
        fn = render_ns['needs_rendering']
        html = '<script id="__NEXT_DATA__">{}</script>'
        self.assertTrue(fn('auto', html, 'content ' * 200))
        self.assertFalse(fn('never', html, 'content ' * 200))
        self.assertFalse(fn('auto', '<main>Ordinary PHP content</main>', 'content ' * 200))

    def test_embedded_and_data_links_without_executing_javascript(self):
        page = production_parser()('<iframe src="/guide.pdf"></iframe><button data-href="/service?id=43">Service</button><a href="javascript:delete()">bad</a>', 'https://example.com/')
        self.assertEqual({l.url for l in page.links}, {'https://example.com/guide.pdf', 'https://example.com/service?id=43'})

    def test_promdelmed_button_files_and_host_scope(self):
        data = json.dumps({'files': [{'uuid': '656c3395-060c-41b6-abf8-0fa98e6b4a6c.pdf', 'extension': 'pdf', 'title': {'first': 'Guide'}}]}).encode()
        links = ns['json_links'](data, 'https://promdelmed.ru/api/catalog/-916')
        self.assertEqual(links, {'https://promdelmed.ru/api/file/download/656c3395-060c-41b6-abf8-0fa98e6b4a6c.pdf': 'Guide'})
        self.assertEqual(ns['json_links'](data, 'https://other.example/api'), {})
        html = ns['discovery_html'](links)
        page = production_parser()(html, 'https://promdelmed.ru/catalog/-916')
        self.assertEqual(len(page.links), 1)
        self.assertEqual(page.text, '')

    def test_json_urls_are_filtered_and_escaped(self):
        links = ns['json_links'](b'{"href":"javascript:bad()","downloadUrl":"/file.pdf","title":"<script>bad()</script>"}', 'https://example.com/api')
        self.assertEqual(list(links), ['https://example.com/file.pdf'])
        self.assertNotIn('<script>', ns['discovery_html'](links))
        self.assertEqual(ns['json_links'](b'{bad', 'https://example.com'), {})

    def test_download_headers_and_pdf_signature(self):
        classify = urls.classify_content_type
        self.assertEqual(classify('application/octet-stream', 'https://example.com/download.php?id=43', ['pdf'], content_disposition='attachment; filename="guide.pdf"'), ('file', 'pdf'))
        self.assertEqual(classify('application/octet-stream', 'https://example.com/download', ['pdf'], b'%PDF-1.7'), ('file', 'pdf'))
        self.assertEqual(classify('text/html', 'https://example.com/guide.pdf', ['pdf']), ('page', ''))
        self.assertEqual(classify('application/octet-stream', 'https://example.com/guide.pdf', []), ('resource', 'PDF'))

if __name__ == '__main__':
    unittest.main()
