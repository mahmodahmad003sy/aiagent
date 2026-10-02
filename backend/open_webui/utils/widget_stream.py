"""In-process bridge from the chat pipeline event emitter to public widget responses."""

from __future__ import annotations

import asyncio
from typing import Optional

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

    @property
    def content(self) -> str:
        return self.final_text if self.final_text is not None else ''.join(self.text_parts)

    def handle_event(self, event: dict) -> None:
        event_type = event.get('type')
        data = event.get('data') or {}
        if not isinstance(data, dict):
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
            if data.get('usage'):
                self.usage = data['usage']
            if data.get('done'):
                self.final_text = get_output_text(data.get('output')) or ''.join(self.text_parts)
                self.queue.put_nowait({'widget_final': {'content': self.final_text}})


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
