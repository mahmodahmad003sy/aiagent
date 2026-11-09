"""Bounded discovery from public JSON loaded by a rendered page; never execute actions."""
import json
import re
from html import escape
from urllib.parse import urlsplit, urlencode

from open_webui.utils.widget_crawl_urls import resolve_href, MAX_LINKED_ITEMS


URL_FIELDS = {'href', 'url', 'link', 'path', 'permalink', 'downloadurl', 'fileurl',
              'documenturl', 'contenturl', 'embedurl', 'targeturl', 'pageurl'}


def json_links(body: bytes, response_url: str) -> dict[str, str]:
    if len(body) > 5 * 1024 * 1024:
        return {}
    try:
        data = json.loads(body)
    except (ValueError, RecursionError):
        return {}
    links = {}
    remaining = 5000
    promdelmed = urlsplit(response_url).hostname in {'promdelmed.ru', 'www.promdelmed.ru'}

    def visit(value, depth=0):
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 16 or len(links) >= MAX_LINKED_ITEMS:
            return
        if isinstance(value, list):
            for child in value[:1000]:
                visit(child, depth + 1)
        elif isinstance(value, dict):
            title = value.get('title') or value.get('name') or value.get('originalname') or ''
            if isinstance(title, dict):
                title = title.get('first', '')
            title = str(title)[:200]
            for key, raw in value.items():
                if str(key).lower().replace('_', '').replace('-', '') not in URL_FIELDS:
                    continue
                # A slug, filesystem path or arbitrary word is not evidence of a URL.
                if (isinstance(raw, str) and (raw.startswith(('https://', 'http://', '/', './', '../', '?'))
                        or str(key).lower() == 'href' or re.search(r'\.(?:pdf|docx?|xlsx?|pptx?|csv|txt|zip)(?:[?#]|$)', raw, re.I))
                        and (url := resolve_href(response_url, raw))):
                    links[url] = title
            # Next/React router objects preserve query IDs, including repeated values.
            pathname, query = value.get('pathname'), value.get('query')
            if isinstance(pathname, str) and pathname.startswith('/') and isinstance(query, dict):
                query = {k: v for k, v in query.items() if isinstance(v, (str, int, float, bool, list))}
                url = resolve_href(response_url, pathname + '?' + urlencode(query, doseq=True))
                if url:
                    links[url] = title
            # Promdelmed's PDF buttons only create anchors after a click. Its
            # public API supplies the same downloadable UUID to the PDF viewer.
            uuid = value.get('uuid')
            if promdelmed and isinstance(uuid, str) and re.fullmatch(
                r'[0-9a-fA-F-]{36}\.[a-zA-Z0-9]{1,5}', uuid
            ) and value.get('extension'):
                url = resolve_href(response_url, '/api/file/download/' + uuid)
                if url:
                    links[url] = title
            for child in value.values():
                if isinstance(child, (dict, list)):
                    visit(child, depth + 1)

    visit(data)
    return links


def html_data_links(soup, page_url: str) -> dict[str, str]:
    """Extract declared routes; do not execute JavaScript or invent routes from IDs."""
    links = {}
    for script in soup.select('script[type="application/json"], script[type="application/ld+json"], script#__NEXT_DATA__, script#__NUXT_DATA__')[:100]:
        links.update(json_links((script.string or '').encode('utf-8'), page_url))
        if len(links) >= MAX_LINKED_ITEMS:
            break
    # Legacy PHP/ASP sites often declare literal navigation in onclick handlers.
    navigation = re.compile(
        r'''(?:\b(?:window\.)?location(?:\.href)?\s*=\s*|\b(?:window\.)?open\s*\(\s*|\b(?:router\.(?:push|replace)|location\.(?:assign|replace))\s*\(\s*)["']([^"'\n]+)["']'''
    )
    for element in soup.select('[onclick]')[:MAX_LINKED_ITEMS]:
        for match in navigation.finditer(element.get('onclick', '')):
            if '${' in match[1] or element.get('onclick', '')[match.end():].lstrip().startswith('+'):
                continue
            if (url := resolve_href(page_url, match[1])):
                links[url] = element.get_text(' ', strip=True)[:200]
    return dict(list(links.items())[:MAX_LINKED_ITEMS])


def discovery_html(links: dict[str, str]) -> str:
    # A separate hidden block contributes links, never article text.
    return '<aside hidden>' + ''.join(
        f'<a href="{escape(url, quote=True)}">{escape(title)}</a>'
        for url, title in list(links.items())[:MAX_LINKED_ITEMS]
    ) + '</aside>'
