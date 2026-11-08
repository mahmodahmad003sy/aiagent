"""Metasolutions Next.js content extraction; pure parsing, no network or app state.

Only the site's public content envelope is read. Translation dictionaries and
layout/configuration metadata must never be treated as page content.
"""
from __future__ import annotations

import json
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

class PageData(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.active = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.active = dict(attrs).get('id') == '__NEXT_DATA__'

    def handle_endtag(self, tag):
        if tag == 'script':
            self.active = False

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)


class ArticleText(HTMLParser):
    BLOCKS = {'p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'h4', 'blockquote', 'tr'}
    IGNORED = {'script', 'style', 'template', 'noscript'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.ignored = []

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORED:
            self.ignored.append(tag)
        if not self.ignored and tag in self.BLOCKS:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if self.ignored:
            if tag == self.ignored[-1]:
                self.ignored.pop()
            return
        if tag in self.BLOCKS:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def clean_html(value: str) -> str:
    parser = ArticleText()
    parser.feed(value)
    return '\n'.join(line for raw in ''.join(parser.parts).splitlines() if (line := ' '.join(raw.split())))


TEXT_FIELDS = ('title', 'fullName', 'subTitle', 'position', 'description',
               'content', 'text', 'question', 'answer')
CONTAINERS = ('item', 'items', 'pageItems', 'detail', 'subServices')


def extract_metasolutions_page(html: str, url: str) -> dict | None:
    """Return known public content, or None so normal rendering can continue.

    This is a site adapter, not a generic dump of arbitrary Next.js application
    state. Depth and item limits bound work on malformed input.
    """
    if urlsplit(url).hostname not in {'metasolutions.ae', 'www.metasolutions.ae'}:
        return None
    parser = PageData()
    parser.feed(html)
    try:
        state = json.loads(''.join(parser.parts))
        response = state['props']['pageProps']['data']
        if response.get('isSuccess') is False:
            return None
        data = response['data']
        if not isinstance(data, dict):
            return None
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
        return None

    item = data.get('item')
    expected_id = parse_qs(urlsplit(url).query).get('id', [None])[0]
    if isinstance(item, dict) and expected_id and str(item.get('id')) != expected_id:
        return None
    detail = data.get('pageDetail')
    detail = detail if isinstance(detail, dict) else {}
    title_source = item if isinstance(item, dict) else detail
    title = clean_html(title_source.get('title', '')) if isinstance(title_source.get('title'), str) else ''
    fragments = []
    blocks = []
    visited = 0

    def visit(value, depth=0):
        nonlocal visited
        visited += 1
        if depth > 16 or visited > 5000:
            return
        if isinstance(value, list):
            for child in value[:1000]:
                visit(child, depth + 1)
        elif isinstance(value, dict):
            fields = []
            for key in TEXT_FIELDS:
                raw = value.get(key)
                if isinstance(raw, str) and (text := clean_html(raw)):
                    fields.append(text)
                    fragments.append(raw)
            if fields:
                blocks.append('\n'.join(fields))
            for key in CONTAINERS:
                if key in value:
                    visit(value[key], depth + 1)

    # A page title alone is not evidence of readable content.
    visit(data)
    sections = data.get('sectionsContent')
    if isinstance(sections, dict):
        for section in list(sections.values())[:100]:
            visit(section)
    description = detail.get('description')
    if isinstance(description, str) and (text := clean_html(description)):
        blocks.insert(0, text)
        fragments.append(description)
    if not blocks:
        return None
    content = '\n\n'.join(dict.fromkeys(([title] if title else []) + blocks))
    return {'title': title, 'content_text': content[:200_000],
            'content_html': '\n'.join(fragments), 'extraction_method': 'next_data_content'}


