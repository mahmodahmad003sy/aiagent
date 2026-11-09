"""In-process bridge from the chat pipeline event emitter to public widget responses."""

from __future__ import annotations

import asyncio
import re
from typing import Optional
from urllib.parse import urlsplit, quote

from open_webui.utils.misc import get_output_text

WIDGET_ERROR_MESSAGE = 'The assistant could not respond. Please try again.'

_turns: dict[str, 'WidgetTurn'] = {}


class WidgetTurn:
    def __init__(self, message_id: str):
        self.message_id = message_id
        self.queue: asyncio.Queue = asyncio.Queue()
        self.text_parts: list[str] = []
        self.final_text: Optional[str] = None
        self.error: Optional[str] = None
        self.usage: Optional[dict] = None
        self.sources: dict[str, str] = {}

    @property
    def content(self) -> str:
        text = self.final_text if self.final_text is not None else ''.join(self.text_parts)
        if not text or self.error:
            return text
        links = []
        for url, title in self.sources.items():
            if url in text:
                continue
            label = re.sub(r'[\[\]\\\r\n<>]', ' ', title).strip()[:160] or 'Source'
            encoded_url = quote(url, safe=":/?#[]@!$&'()*+,;=%~_-.")
            links.append(f'- [{label}](<{encoded_url}>)')
        return text + ('\n\n**Source links**\n' + '\n'.join(links) if links else '')

    def add_source(self, data: dict) -> None:
        source = data.get('source') or {}
        if not isinstance(source, dict):
            source = {}
        records = [source] + [m for m in (data.get('metadata') or []) if isinstance(m, dict)]
        for record in records:
            nested = record.get('data') if isinstance(record.get('data'), dict) else {}
            url = record.get('source_url') or nested.get('source_url') or record.get('url') or record.get('source')
            if not isinstance(url, str) or len(self.sources) >= 8:
                continue
            try:
                parts = urlsplit(url)
                if parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username or parts.password:
                    continue
            except ValueError:
                continue
            title = record.get('source_name') or nested.get('source_name') or record.get('name') or source.get('name') or parts.hostname
            self.sources[url] = str(title)

    def handle_event(self, event: dict) -> None:
        event_type = event.get('type')
        data = event.get('data') or {}
        if not isinstance(data, dict):
            return

        if event_type == 'source':
            self.add_source(data)
            if self.final_text is not None:
                self.queue.put_nowait({'widget_final': {'content': self.content}})
            return

        if event_type == 'response:completion':
            data_type = data.get('type')
            if data_type == 'response.output_text.delta' and isinstance(data.get('delta'), str):
                self.text_parts.append(data['delta'])
                self.queue.put_nowait({'choices': [{'delta': {'content': data['delta']}}]})
            elif data_type == 'response.output_item.added':
                item = data.get('item') or {}
                if item.get('type') == 'function_call':
                    self.queue.put_nowait({'widget_status': {'state': 'tool', 'name': item.get('name') or ''}})
            return

        if event_type == 'chat:message:error' or (event_type == 'chat:completion' and data.get('error')):
            error = data.get('error')
            self.error = (error.get('content') if isinstance(error, dict) else str(error)) or 'error'
            self.queue.put_nowait({'widget_error': {'message': WIDGET_ERROR_MESSAGE}})
            return

        if event_type == 'chat:completion':
            for source in data.get('sources') or []:
                if isinstance(source, dict):
                    self.add_source(source)
            if data.get('usage'):
                self.usage = data['usage']
            if data.get('done'):
                self.final_text = get_output_text(data.get('output')) or ''.join(self.text_parts)
                self.queue.put_nowait({'widget_final': {'content': self.content}})


def register_widget_turn(message_id: str) -> WidgetTurn:
    turn = WidgetTurn(message_id)
    _turns[message_id] = turn
    return turn


def unregister_widget_turn(message_id: str) -> None:
    _turns.pop(message_id, None)


def publish_widget_event(message_id: Optional[str], event: dict) -> None:
    if not message_id:
        return
    turn = _turns.get(message_id)
    if turn is None:
        return
    try:
        turn.handle_event(event)
    except Exception:
        pass
