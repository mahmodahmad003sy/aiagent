"""Exercise production HTML parsing without starting the app/database."""
import ast
import json
import sys
import unittest
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
exec((ROOT / 'backend/open_webui/utils/widget_crawl_next_data.py').read_text(encoding='utf-8'))
exec((ROOT / 'backend/open_webui/utils/widget_crawl_urls.py').read_text(encoding='utf-8'))


def payload(data, **extra):
    state = {'props': {'pageProps': {'data': {'data': data, 'isSuccess': True}, **extra}}}
    return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(state).replace('<', '\\u003c') + '</script>'


def production_parser():
    path = ROOT / 'backend/open_webui/utils/widget_crawler.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    names = {'ParsedPage', 'ParsedLink', '_clean', 'parse_html_page'}
    nodes = [node for node in tree.body if getattr(node, 'name', '') in names
             or isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == 'REMOVED_TAGS' for t in node.targets)]
    ns = dict(globals())
    discovery = ast.parse((ROOT / 'backend/open_webui/utils/widget_crawl_discovery.py').read_text(encoding='utf-8'))
    discovery.body = [node for node in discovery.body if not (isinstance(node, ast.ImportFrom) and (node.module or '').startswith('open_webui'))]
    exec(compile(discovery, 'discovery', 'exec'), ns)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), ns)
    return ns['parse_html_page']


class NextDataTests(unittest.TestCase):
    def setUp(self):
        self.parse = production_parser()
        self.url = 'https://metasolutions.ae/team'
        self.html = payload({'pageDetail': {'title': 'Team'}, 'pageItems': [
            {'fullName': 'Test Person', 'position': 'Developer', 'image': 'ignore.jpg'}]},
            __namespaces={'common': {'text': 'Translation noise'}})

    def test_team_production_parser(self):
        result = self.parse(self.html, self.url)
        self.assertEqual(result.title, 'Team')
        self.assertEqual(result.text, 'Team\n\nTest Person\nDeveloper')
        self.assertNotIn('Translation', result.text)
        self.assertNotIn('ignore.jpg', result.text)

    def test_regular_html_preserved(self):
        body = 'This is the visible rendered page content. ' * 4
        result = self.parse('<main>' + body + '</main>' + self.html, self.url)
        self.assertEqual(result.text, body.strip())

    def test_other_host_ignored(self):
        self.assertEqual(self.parse(self.html, 'https://example.com/team').text, '')

    def test_malformed_and_empty_payloads(self):
        for html in ('<script id="__NEXT_DATA__">{bad</script>', payload({}),
                     payload({'pageDetail': {'title': 'Team'}}), payload({'item': None})):
            self.assertEqual(self.parse(html, self.url).text, '')

    def test_listings_sections_and_real_links(self):
        item = {'title': 'Service', 'description': '<p>Useful description <a href="/contact">Contact</a><a href="javascript:bad()">Bad</a></p>'}
        for data in ({'pageItems': {'items': [item]}}, {'sectionsContent': {'services': {'items': [item]}}}):
            result = self.parse(payload(data), self.url)
            self.assertIn('Useful description', result.text)
            self.assertEqual([link.url for link in result.links], ['https://metasolutions.ae/contact'])

    def test_article_id_mismatch(self):
        self.assertIsNone(extract_metasolutions_page(payload({'item': {'id': 2, 'title': 'Wrong'}}), self.url + '?id=1'))


if __name__ == '__main__':
    unittest.main()
