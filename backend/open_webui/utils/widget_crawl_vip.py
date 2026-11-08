"""Paid page fetching via 2Captcha. Never retry task creation automatically."""
import asyncio
import json
import os
from urllib.parse import quote, urlparse

import aiohttp
import markdown
from open_webui.retrieval.web.utils import validate_url
from open_webui.utils.widget_crawl_fetch import FetchResult

BASE_URL = 'https://scraper.2captcha.com'
VIP_POLL_INTERVAL_SECONDS = 10
VIP_POLL_DEADLINE_SECONDS = 300
VIP_SYNC_TIMEOUT_SECONDS = 135


def api_key():
    return os.environ.get('SCRAPER_API_KEY', '').strip()


def vip_wait_selector(url: str, selector: str) -> str:
    """Match tools/crawler-lab/2captcha-request.ps1 defaults when no selector is configured."""
    selector = (selector or '').strip()
    if selector:
        return selector
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    path = (parsed.path or '').rstrip('/') or ''
    if host in ('epc.ae', 'www.epc.ae') and path in ('', '/en', '/en/home'):
        return 'a[href*="/en/details/"]'
    return ''


def response_http_code(data: dict) -> int | None:
    code = data.get('http_code')
    if code is None:
        status = data.get('status')
        if isinstance(status, int):
            code = status
    return code


def decode_page(url, data, max_bytes):
    status = response_http_code(data)
    body = data.get('body')
    if status != 200 or data.get('status') in ('warn', 'error') or not isinstance(body, str) or not body.strip():
        return FetchResult(url, 'http_error', error='VIP service returned an error, warning or empty content.')
    if any(marker in body.lower() for marker in ('please solve this captcha', 'request unblock to the website', 'your activity and behavior on this site made us think')):
        return FetchResult(url, 'blocked', error='VIP service returned a protection page.')
    html = markdown.markdown(body).encode('utf-8')
    if len(html) > max_bytes:
        return FetchResult(url, 'too_large')
    return FetchResult(url, 'ok', http_status=200, content_type='text/html; charset=utf-8', body=html, content_length=len(html))


async def fetch_vip(url, selector, max_bytes, check_cancel):
    await asyncio.to_thread(validate_url, url)
    token = api_key()
    if not token:
        return FetchResult(url, 'blocked', error='VIP crawling requires SCRAPER_API_KEY on the server.')
    wait_selector = vip_wait_selector(url, selector)
    payload = dict(task_type='scrape', url=url, data_format='markdown', format='json', timeout=120)
    if wait_selector:
        payload['waitFor'] = dict(element=wait_selector, checkVisible=True)
    async def read(response):
        raw = bytearray()
        async for chunk in response.content.iter_chunked(65536):
            raw.extend(chunk)
            if len(raw) > max_bytes * 8:
                raise ValueError('Response too large')
        return json.loads(raw)
    try:
        session_timeout = max(VIP_SYNC_TIMEOUT_SECONDS + 5, VIP_POLL_DEADLINE_SECONDS + VIP_SYNC_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=session_timeout), trust_env=False) as session:
            check_cancel()
            async with session.post(
                BASE_URL + '/tasks/sync',
                json=payload,
                headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
                timeout=aiohttp.ClientTimeout(total=VIP_SYNC_TIMEOUT_SECONDS),
                allow_redirects=False,
            ) as response:
                status = response.status
                if status in (401, 402, 403):
                    raise RuntimeError(f'VIP service HTTP {status}: check server key, account permissions and balance. Crawl stopped.')
                if status not in (200, 408):
                    return FetchResult(url, 'http_error', error=f'VIP service HTTP {status}. Check account balance and key; no duplicate task submitted.')
                data = await read(response)
            if status == 408:
                task_id = data.get('response_id')
                if not isinstance(task_id, str) or not task_id:
                    raise ValueError('Missing task ID')
                deadline = asyncio.get_running_loop().time() + VIP_POLL_DEADLINE_SECONDS
                while asyncio.get_running_loop().time() < deadline:
                    check_cancel()
                    async with session.get(BASE_URL + '/tasks/result/' + quote(task_id, safe=''),
                                           timeout=aiohttp.ClientTimeout(total=45), allow_redirects=False) as response:
                        if response.status == 200:
                            data = await read(response)
                            break
                        if response.status != 202:
                            return FetchResult(url, 'http_error', error=f'VIP task failed (HTTP {response.status}).')
                    await asyncio.sleep(VIP_POLL_INTERVAL_SECONDS)
                else:
                    return FetchResult(url, 'timeout', error='VIP task remains pending. No duplicate task was submitted; check provider history before re-crawling.')
            return decode_page(url, data, max_bytes)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return FetchResult(url, 'connection_error', error='VIP request failed or timed out. No automatic resubmission; check provider history before re-crawling.')
