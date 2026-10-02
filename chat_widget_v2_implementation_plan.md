# Chat Widget V2 — Implementation Instructions

Scope: three features on top of the existing V1 widget.

1. MCP tools on/off per widget.
2. Widget appearance customization (avatar, colors, font, sizes, radius, position).
3. Widget conversations saved as normal Open WebUI chats owned by the widget creator.

Follow the steps in order. Do not change anything that is not listed here.

Files touched:

| File | Change |
|---|---|
| `backend/open_webui/migrations/versions/7c2e9a41b5d3_chat_widget_v2.py` | new |
| `backend/open_webui/models/chat_widgets.py` | edit |
| `backend/open_webui/utils/widget_stream.py` | new |
| `backend/open_webui/socket/main.py` | edit (one hook) |
| `backend/open_webui/routers/widgets.py` | edit |
| `backend/open_webui/static/widget/chat-widget.js` | edit |
| `src/lib/apis/widgets/index.ts` | edit |
| `src/lib/components/workspace/ChatWidgets.svelte` | edit |
| `src/lib/components/workspace/ChatWidgetPreview.svelte` | new |

---

## 1. Database migration

Create `backend/open_webui/migrations/versions/7c2e9a41b5d3_chat_widget_v2.py`:

- `revision = '7c2e9a41b5d3'`
- `down_revision = 'e5f6a7b8c9d0'`
- Use the same "inspect first, then add" style as `e5f6a7b8c9d0_add_chat_widget_tables.py`. Before each `op.add_column`, check `[c['name'] for c in inspector.get_columns(table)]` and skip the column if it already exists.

`upgrade()` adds:

| Table | Column | Type | Null | Default |
|---|---|---|---|---|
| `chat_widget` | `theme` | `sa.JSON()` | yes | none |
| `chat_widget` | `mcp_enabled` | `sa.Boolean()` | no | `server_default=sa.false()` |
| `chat_widget` | `mcp_tool_ids` | `sa.JSON()` | yes | none |
| `chat_widget` | `folder_id` | `sa.Text()` | yes | none |
| `chat_widget_session` | `chat_id` | `sa.Text()` | yes | none |
| `chat_widget_session` | `chat_last_message_id` | `sa.Text()` | yes | none |

Also create the index `ix_chat_widget_session_chat_id` on `chat_widget_session(chat_id)`.

Use `op.batch_alter_table(...)` for every add/drop so SQLite works.

`downgrade()` drops the index first, then all 6 columns, in reverse order.

---

## 2. Models — `backend/open_webui/models/chat_widgets.py`

### 2.1 Theme schema

Add these at module level, above `ChatWidget`:

```python
import re
from typing import Literal

HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')
AVATAR_DATA_URL_RE = re.compile(r'^data:image/(png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+$')
AVATAR_MAX_LENGTH = 150_000
MCP_TOOL_ID_PREFIX = 'server:mcp:'
MAX_MCP_TOOL_IDS = 20


class ChatWidgetTheme(BaseModel):
    model_config = ConfigDict(extra='forbid')

    primary_color: str = '#111827'
    primary_text_color: str = '#ffffff'
    header_background_color: str = '#ffffff'
    header_text_color: str = '#111827'
    background_color: str = '#fafafa'
    assistant_bubble_color: str = '#ffffff'
    assistant_text_color: str = '#111827'
    user_bubble_color: str = '#111827'
    user_text_color: str = '#ffffff'

    font_family: Literal['system', 'arial', 'verdana', 'tahoma', 'trebuchet', 'georgia', 'times', 'courier'] = 'system'
    font_size: int = Field(default=14, ge=12, le=20)

    panel_radius: int = Field(default=12, ge=0, le=24)
    bubble_radius: int = Field(default=12, ge=0, le=24)
    panel_width: int = Field(default=390, ge=300, le=480)
    panel_height: int = Field(default=640, ge=400, le=760)

    launcher_shape: Literal['circle', 'rounded', 'square'] = 'circle'
    launcher_size: int = Field(default=58, ge=44, le=72)
    launcher_icon: Literal['chat', 'avatar'] = 'chat'

    position: Literal['right', 'left'] = 'right'
    offset_x: int = Field(default=20, ge=0, le=120)
    offset_y: int = Field(default=20, ge=0, le=120)

    avatar_url: Optional[str] = None
    header_title: Optional[str] = Field(default=None, max_length=60)
    header_subtitle: Optional[str] = Field(default=None, max_length=80)
    input_placeholder: str = Field(default='Type a message', min_length=1, max_length=120)
    show_status: bool = True

    @field_validator(
        'primary_color', 'primary_text_color', 'header_background_color', 'header_text_color',
        'background_color', 'assistant_bubble_color', 'assistant_text_color',
        'user_bubble_color', 'user_text_color',
    )
    @classmethod
    def validate_color(cls, value: str) -> str:
        if not HEX_COLOR_RE.match(value or ''):
            raise ValueError('Colors must be in #RRGGBB format')
        return value.lower()

    @field_validator('avatar_url')
    @classmethod
    def validate_avatar(cls, value: Optional[str]) -> Optional[str]:
        if value is None or value == '':
            return None
        if len(value) > AVATAR_MAX_LENGTH or not AVATAR_DATA_URL_RE.match(value):
            raise ValueError('Avatar must be a PNG, JPEG, WEBP or GIF image under 150 KB')
        return value

    @field_validator('header_title', 'header_subtitle')
    @classmethod
    def blank_to_none(cls, value: Optional[str]) -> Optional[str]:
        value = (value or '').strip()
        return value or None

    @field_validator('input_placeholder')
    @classmethod
    def strip_placeholder(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError('Placeholder cannot be empty')
        return value


def normalize_mcp_tool_ids(value: list[str] | None) -> list[str]:
    ids = []
    for tool_id in value or []:
        tool_id = (tool_id or '').strip()
        if not tool_id:
            continue
        if not tool_id.startswith(MCP_TOOL_ID_PREFIX):
            raise ValueError(f'Invalid MCP tool id: {tool_id}')
        if tool_id not in ids:
            ids.append(tool_id)
    if len(ids) > MAX_MCP_TOOL_IDS:
        raise ValueError(f'A widget can use at most {MAX_MCP_TOOL_IDS} MCP servers')
    return ids
```

Rules:
- SVG avatars are not allowed (XSS risk). Do not add `svg` to the regex.
- Colors are always stored in lowercase.

### 2.2 SQLAlchemy columns

Add to `ChatWidget`:

```python
theme = Column(JSON, nullable=True)
mcp_enabled = Column(Boolean, nullable=False, default=False)
mcp_tool_ids = Column(JSON, nullable=True)
folder_id = Column(Text, nullable=True)
```

Add to `ChatWidgetSession`:

```python
chat_id = Column(Text, nullable=True, index=True)
chat_last_message_id = Column(Text, nullable=True)
```

### 2.3 Pydantic models

`ChatWidgetModel` — add:

```python
theme: ChatWidgetTheme = Field(default_factory=ChatWidgetTheme)
mcp_enabled: bool = False
mcp_tool_ids: list[str] = Field(default_factory=list)
folder_id: Optional[str] = None

@field_validator('theme', mode='before')
@classmethod
def default_theme(cls, value):
    return value or {}

@field_validator('mcp_tool_ids', mode='before')
@classmethod
def default_mcp_tool_ids(cls, value):
    return value or []
```

This guarantees that V1 widgets (NULL theme) always return a full default theme.

`ChatWidgetSessionModel` — add:

```python
chat_id: Optional[str] = None
chat_last_message_id: Optional[str] = None
```

`ChatWidgetForm` — add:

```python
theme: ChatWidgetTheme = Field(default_factory=ChatWidgetTheme)
mcp_enabled: bool = False
mcp_tool_ids: list[str] = Field(default_factory=list)
```

Add a `field_validator('mcp_tool_ids')` that returns `normalize_mcp_tool_ids(value)`.

`ChatWidgetUpdateForm` — add:

```python
theme: Optional[ChatWidgetTheme] = None
mcp_enabled: Optional[bool] = None
mcp_tool_ids: Optional[list[str]] = None
```

Its validator returns `None` if `value is None`, otherwise `normalize_mcp_tool_ids(value)`.

`folder_id` is never accepted from forms.

### 2.4 Table methods

`ChatWidgetTable.insert_new_widget`: `form_data.model_dump()` already turns `theme` into a dict. No change is needed.

`ChatWidgetTable.update_widget_by_id_and_user_id`: no change. `theme` is replaced as a whole object; the UI always sends the full theme.

Add to `ChatWidgetTable`:

```python
async def set_folder_id(self, id: str, folder_id: Optional[str], db: Optional[AsyncSession] = None) -> None:
    async with get_async_db_context(db) as db:
        widget = await db.get(ChatWidget, id)
        if widget:
            widget.folder_id = folder_id
            await db.commit()
```

Add to `ChatWidgetSessionTable`:

```python
async def update_chat_link(
    self,
    id: str,
    chat_id: Optional[str] = None,
    chat_last_message_id: Optional[str] = None,
    db: Optional[AsyncSession] = None,
) -> None:
    async with get_async_db_context(db) as db:
        session = await db.get(ChatWidgetSession, id)
        if not session:
            return
        if chat_id is not None:
            session.chat_id = chat_id
        if chat_last_message_id is not None:
            session.chat_last_message_id = chat_last_message_id
        await db.commit()
```

---

## 3. Stream bridge — new file `backend/open_webui/utils/widget_stream.py`

Why this file exists: V1 calls `open_webui.utils.chat.generate_chat_completion`. That function calls the provider directly. It skips the Open WebUI middleware, so MCP tools never run and nothing is saved to `chat`. V2 must call the full pipeline, `request.app.state.CHAT_COMPLETION_HANDLER` (the same handler automations use). With a saved `chat_id` and `message_id`, that pipeline sends its output through the socket **event emitter**, not through the HTTP response. This file captures those emitter events for one assistant message and converts them into a simple SSE stream for the widget.

```python
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
```

Rules:
- Reasoning deltas (`response.reasoning_text.delta`) are ignored on purpose. Visitors must not see model reasoning.
- The real error text goes into `turn.error`, which is saved in the DB. The visitor only receives `WIDGET_ERROR_MESSAGE`.
- The registry is in-memory. This is correct even with several workers, because the pipeline task runs in the same process as the widget request that started it.

### 3.1 Hook into the event emitter — `backend/open_webui/socket/main.py`

In `get_event_emitter`, inside the inner `async def __event_emitter__(event_data):`, insert this directly after the line `message_id = request_info['message_id']`:

```python
        publish_widget_event(message_id, event_data)
```

Add the import at the top of the file, next to the other `open_webui.utils` imports:

```python
from open_webui.utils.widget_stream import publish_widget_event
```

Make no other change in this file.

---

## 4. Router — `backend/open_webui/routers/widgets.py`

### 4.1 Imports

Remove: `from open_webui.utils.chat import generate_chat_completion`.

Add:

```python
import asyncio
import time
from datetime import timedelta

from open_webui.models.chats import ChatForm, Chats
from open_webui.models.folders import FolderForm, Folders
from open_webui.utils.auth import create_token
from open_webui.utils.widget_stream import register_widget_turn, unregister_widget_turn
```

Also import `ChatWidgetTheme` and `MCP_TOOL_ID_PREFIX` from `open_webui.models.chat_widgets`.

Delete these functions; they are no longer used: `_messages_for_completion`, `_extract_response_content`, `_extract_stream_delta`, `_stream_widget_response`. Keep `_message_content_as_text` and `_save_assistant_message`.

Add constants:

```python
PUBLIC_WIDGET_STREAM_KEEPALIVE = 15  # seconds
WIDGET_OWNER_TOKEN_TTL = timedelta(minutes=15)
WIDGET_FOLDER_PREFIX = 'Widget: '
```

### 4.2 MCP validation on create and update

Add:

```python
async def _ensure_mcp_tool_access(request: Request, tool_ids: list[str], user, db: AsyncSession) -> None:
    if not tool_ids:
        return
    from open_webui.routers.tools import get_tools as list_user_tools

    available = {
        tool.id
        for tool in await list_user_tools(request, query=None, user=user, db=db)
        if tool.id.startswith(MCP_TOOL_ID_PREFIX)
    }
    missing = [tool_id for tool_id in tool_ids if tool_id not in available]
    if missing:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f'MCP server not available: {missing[0]}')
```

In `create_widget`, after `_ensure_model_access`:

```python
if form_data.mcp_enabled and not form_data.mcp_tool_ids:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Select at least one MCP server')
await _ensure_mcp_tool_access(request, form_data.mcp_tool_ids, user, db)
```

In `update_widget_by_id`, before the update call:

```python
existing = await ChatWidgets.get_widget_by_id_and_user_id(widget_id, user.id, db=db)
if not existing:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)
effective_enabled = form_data.mcp_enabled if form_data.mcp_enabled is not None else existing.mcp_enabled
effective_ids = form_data.mcp_tool_ids if form_data.mcp_tool_ids is not None else existing.mcp_tool_ids
if effective_enabled and not effective_ids:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Select at least one MCP server')
if form_data.mcp_tool_ids is not None:
    await _ensure_mcp_tool_access(request, form_data.mcp_tool_ids, user, db)
```

MCP ids are not re-checked at chat time. The pipeline's `connect_mcp_server` already skips servers that were disabled or whose access was revoked.

### 4.3 Public config

Change `PublicWidgetConfigResponse` to:

```python
class PublicWidgetConfigResponse(BaseModel):
    id: str
    name: str
    welcome_message: Optional[str] = None
    theme: ChatWidgetTheme
```

Return `theme=widget.theme` in `get_public_widget_config`. Never return `mcp_enabled`, `mcp_tool_ids`, `folder_id`, `system_prompt`, `model_id` or `user_id` publicly.

### 4.4 Owner folder and chat creation

Add:

```python
async def _ensure_widget_folder(widget: ChatWidgetModel) -> str:
    if widget.folder_id and await Folders.get_folder_by_id_and_user_id(widget.folder_id, widget.user_id):
        return widget.folder_id

    name = f'{WIDGET_FOLDER_PREFIX}{widget.name}'[:100]
    folder = await Folders.get_folder_by_parent_id_and_user_id_and_name(None, widget.user_id, name)
    if not folder:
        folder = await Folders.insert_new_folder(widget.user_id, FolderForm(name=name), None)
    await ChatWidgets.set_folder_id(widget.id, folder.id)
    return folder.id


def _chat_title(text: str) -> str:
    title = ' '.join((text or '').split())
    return (title[:57] + '...') if len(title) > 60 else (title or 'Widget chat')


async def _ensure_session_chat(
    widget: ChatWidgetModel,
    session: ChatWidgetSessionModel,
    first_message: str,
) -> tuple[str, Optional[str]]:
    """Return (chat_id, parent_message_id) for the next user message."""
    if session.chat_id and await Chats.get_chat_by_id_and_user_id(session.chat_id, widget.user_id):
        return session.chat_id, session.chat_last_message_id

    folder_id = await _ensure_widget_folder(widget)

    # Backfill: sessions created before V2 (or whose chat the owner deleted) keep their history.
    existing = await ChatWidgetMessages.get_messages_by_session_id_and_widget_id(session.id, widget.id)
    history: dict[str, dict] = {}
    flat: list[dict] = []
    last_id: Optional[str] = None
    first_user_text = None
    for message in existing:
        if message.role not in {'user', 'assistant'}:
            continue
        content = _message_content_as_text(message.content)
        if message.role == 'user' and first_user_text is None:
            first_user_text = content
        message_id = str(uuid4())
        history[message_id] = {
            'id': message_id,
            'parentId': last_id,
            'childrenIds': [],
            'role': message.role,
            'content': content,
            'timestamp': message.created_at,
            **({'model': widget.model_id, 'done': True} if message.role == 'assistant' else {'models': [widget.model_id]}),
        }
        if last_id:
            history[last_id]['childrenIds'].append(message_id)
        flat.append({'role': message.role, 'content': content})
        last_id = message_id

    chat_id = str(uuid4())
    await Chats.insert_new_chat(
        chat_id,
        widget.user_id,
        ChatForm(
            folder_id=folder_id,
            chat={
                'id': chat_id,
                'title': _chat_title(first_user_text or first_message),
                'models': [widget.model_id],
                'history': {'currentId': last_id, 'messages': history},
                'messages': flat,
                'tags': [],
                'timestamp': int(time.time() * 1000),
                'meta': {
                    'widget_id': widget.id,
                    'widget_session_id': session.id,
                    'visitor_id': session.visitor_id,
                },
            },
        ),
    )
    await ChatWidgetSessions.update_chat_link(session.id, chat_id=chat_id, chat_last_message_id=last_id)

    from open_webui.socket.main import sio

    await sio.emit(
        'events',
        {'chat_id': chat_id, 'message_id': None, 'data': {'type': 'chat:list'}},
        room=f'user:{widget.user_id}',
    )
    return chat_id, last_id
```

Rules:
- One widget session = one Open WebUI chat. All chats of a widget go into one folder, named `Widget: <widget name>`, owned by the widget creator.
- If the owner deletes the folder or the chat, the next visitor message recreates it (with backfill).
- Renaming a widget does not rename its existing folder.
- Do **not** pass `internal_meta` to `insert_new_chat`. Internal chats are hidden from the sidebar.

### 4.5 Rewrite `create_public_widget_chat_message`

Keep everything up to and including the session get/create block exactly as in V1. Replace everything after it with the steps below, in this exact order.

**Step 1 — ensure the owner chat** (this must run before the widget user message is inserted, so the backfill does not duplicate it):

```python
chat_id, parent_message_id = await _ensure_session_chat(widget, session, form_data.message)
```

**Step 2 — save the widget user message.** Keep the existing `ChatWidgetMessages.insert_new_message(...)` call unchanged.

**Step 3 — build the pipeline payload:**

```python
user_message_id = str(uuid4())
assistant_message_id = str(uuid4())

messages = []
if widget.system_prompt:
    messages.append({'role': 'system', 'content': widget.system_prompt})
messages.append({'role': 'user', 'content': form_data.message})

form_payload = {
    'model': widget.model_id,
    'messages': messages,
    'stream': True,
    'chat_id': chat_id,
    'id': assistant_message_id,
    'user_message': {
        'id': user_message_id,
        'parentId': parent_message_id,
        'childrenIds': [],
        'role': 'user',
        'content': form_data.message,
        'timestamp': int(time.time()),
        'models': [widget.model_id],
    },
    'params': {'tool_approval_mode': 'full'},
    'features': {},
}
if widget.mcp_enabled and widget.mcp_tool_ids:
    form_payload['tool_ids'] = list(widget.mcp_tool_ids)
```

The payload must contain:
- No `session_id`. Without it, `chat_completion` takes the synchronous path, so this request owns the run. It also keeps builtin tools (web search, memory, knowledge, and so on) out, which matches the V1 scope.
- No `parent_id` key. A `chat_id` is always present, so the pipeline uses its "existing chat" branch. That branch saves the user message, the assistant placeholder and the final output into the owner's chat.
- `'stream': True` always, even if the visitor asked for `stream: false`. The pipeline only runs tool calls on its streaming path. The visitor's `stream` flag only decides the HTTP response format (Step 6).
- Conversation history is not sent. The pipeline loads it from the chat DB by following `parentId`, which keeps tool-call outputs. Only the system prompt and the new message are sent.

**Step 4 — run the pipeline in a task:**

```python
request.state.token = create_token(
    data={'id': owner.id, 'typ': 'widget'},
    expires_delta=WIDGET_OWNER_TOKEN_TTL,
)  # needed by MCP servers using auth_type "session"

turn = register_widget_turn(assistant_message_id)
widget_id, session_id, model_id = widget.id, session.id, widget.model_id

async def run_turn():
    try:
        await request.app.state.CHAT_COMPLETION_HANDLER(request, form_payload, user=owner)
    except HTTPException as exc:
        turn.handle_event({'type': 'chat:message:error', 'data': {'error': {'content': str(exc.detail)}}})
    except Exception as exc:
        turn.handle_event({'type': 'chat:message:error', 'data': {'error': {'content': str(exc)}}})
    finally:
        try:
            await _save_assistant_message(
                session_id,
                widget_id,
                model_id,
                turn.content,
                usage=turn.usage,
                error={'content': turn.error} if turn.error else None,
                db=None,
            )
            await ChatWidgetSessions.update_chat_link(session_id, chat_last_message_id=assistant_message_id)
        finally:
            unregister_widget_turn(assistant_message_id)
            turn.queue.put_nowait(None)  # end-of-stream sentinel

task = asyncio.create_task(run_turn())
```

Rules:
- Always pass `db=None` inside `run_turn`. It can outlive the request-scoped `db` session.
- `chat_last_message_id` is updated even when there was an error. The assistant placeholder exists in the chat in both cases, so the next message must chain to it.
- Never cancel `task` when the visitor disconnects. The answer must still be saved to the owner's chat and the widget tables.

**Step 5 — streaming response** (when `form_data.stream` is true):

```python
async def event_stream():
    yield f'data: {JSONCodec.dumps({"widget": {"session_id": session_id, "message_id": message.id}})}\n\n'
    while True:
        try:
            item = await asyncio.wait_for(turn.queue.get(), timeout=PUBLIC_WIDGET_STREAM_KEEPALIVE)
        except asyncio.TimeoutError:
            yield ': ping\n\n'
            continue
        if item is None:
            break
        yield f'data: {JSONCodec.dumps(item)}\n\n'
    yield 'data: [DONE]\n\n'

stream_response = StreamingResponse(event_stream(), media_type='text/event-stream')
stream_response.headers['Cache-Control'] = 'no-cache'
stream_response.headers['X-Accel-Buffering'] = 'no'
_set_public_cors_headers(stream_response, request, widget)
return stream_response
```

`asyncio.wait_for` is safe here because it only wraps `queue.get()`, not the pipeline task.

**Step 6 — non-streaming response** (when `form_data.stream` is false):

```python
await task
return PublicWidgetChatResponse(
    widget_id=widget.id,
    session_id=session.id,
    message_id=message.id,
    assistant_message_id=None,
    content=turn.content if not turn.error else WIDGET_ERROR_MESSAGE,
)
```

Import `WIDGET_ERROR_MESSAGE` from `open_webui.utils.widget_stream`.

**SSE events sent to the widget** (this is the full contract; document nothing else):

| Payload | Meaning |
|---|---|
| `{"widget": {"session_id", "message_id"}}` | always first |
| `{"choices": [{"delta": {"content": "..."}}]}` | text delta |
| `{"widget_status": {"state": "tool", "name": "..."}}` | a tool call started |
| `{"widget_final": {"content": "..."}}` | full final text; replaces the bubble |
| `{"widget_error": {"message": "..."}}` | generic failure |
| `: ping` (SSE comment) | keepalive, ignore |
| `[DONE]` | end |

### 4.6 Session deletion also deletes the chat

In `delete_widget_session`, load the session first with `get_session_by_id_and_widget_id`. If `session.chat_id` is set, call `await Chats.delete_chat_by_id_and_user_id(session.chat_id, widget.user_id)` before deleting the session.

Deleting a whole widget (`delete_widget_by_id`) does **not** delete chats or the folder. They remain the owner's history.

---

## 5. Embed script — `backend/open_webui/static/widget/chat-widget.js`

### 5.1 Theme application

Add the font map at the top of the IIFE:

```js
var FONT_STACKS = {
	system: 'Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif',
	arial: 'Arial,Helvetica,sans-serif',
	verdana: 'Verdana,Geneva,sans-serif',
	tahoma: 'Tahoma,Geneva,sans-serif',
	trebuchet: '"Trebuchet MS",Helvetica,sans-serif',
	georgia: 'Georgia,serif',
	times: '"Times New Roman",Times,serif',
	courier: '"Courier New",Courier,monospace'
};
var LAUNCHER_RADIUS = { circle: '999px', rounded: '16px', square: '6px' };
```

Add `function applyTheme(theme)`, called in `loadConfig` success right after `config = data;`:

```js
function applyTheme(theme) {
	theme = theme || {};
	var vars = {
		'--owui-primary': theme.primary_color || '#111827',
		'--owui-on-primary': theme.primary_text_color || '#ffffff',
		'--owui-header-bg': theme.header_background_color || '#ffffff',
		'--owui-header-fg': theme.header_text_color || '#111827',
		'--owui-bg': theme.background_color || '#fafafa',
		'--owui-assistant-bg': theme.assistant_bubble_color || '#ffffff',
		'--owui-assistant-fg': theme.assistant_text_color || '#111827',
		'--owui-user-bg': theme.user_bubble_color || '#111827',
		'--owui-user-fg': theme.user_text_color || '#ffffff',
		'--owui-font': FONT_STACKS[theme.font_family] || FONT_STACKS.system,
		'--owui-font-size': (theme.font_size || 14) + 'px',
		'--owui-panel-radius': (theme.panel_radius != null ? theme.panel_radius : 12) + 'px',
		'--owui-bubble-radius': (theme.bubble_radius != null ? theme.bubble_radius : 12) + 'px',
		'--owui-launcher-radius': LAUNCHER_RADIUS[theme.launcher_shape] || LAUNCHER_RADIUS.circle,
		'--owui-launcher-size': (theme.launcher_size || 58) + 'px',
		'--owui-offset-x': (theme.offset_x != null ? theme.offset_x : 20) + 'px',
		'--owui-offset-y': (theme.offset_y != null ? theme.offset_y : 20) + 'px',
		'--owui-panel-width': (theme.panel_width || 390) + 'px',
		'--owui-panel-height': (theme.panel_height || 640) + 'px'
	};
	Object.keys(vars).forEach(function (key) {
		root.style.setProperty(key, vars[key]);
	});

	root.classList.toggle('owui-left', theme.position === 'left');
	root.classList.toggle('owui-hide-status', theme.show_status === false);
	input.placeholder = theme.input_placeholder || 'Type a message';
	if (theme.header_title) title.textContent = theme.header_title;

	if (theme.avatar_url) {
		setAvatarImage(root.querySelector('.owui-avatar'), theme.avatar_url, 'owui-avatar-img');
		if (theme.launcher_icon === 'avatar') {
			launcher.classList.add('owui-launcher-has-img');
			setAvatarImage(launcher, theme.avatar_url, 'owui-launcher-img');
		}
	}
}

function setAvatarImage(container, src, className) {
	var img = container.querySelector('img.' + className);
	if (!img) {
		img = document.createElement('img');
		img.className = className;
		img.alt = '';
		container.insertBefore(img, container.firstChild);
	}
	img.src = src;
}
```

Changes to existing code:
- In `loadConfig` success, replace `title.textContent = data.name || 'Chat';` with `title.textContent = data.name || 'Chat'; applyTheme(data.theme);`. The order matters: `header_title` overrides the name.
- Change `setStatus(text)` so the visible text is `config && config.theme && config.theme.header_subtitle && text === 'Online' ? config.theme.header_subtitle : text`. Keep `data-status` set from the raw `text`.
- Images are set only through `img.src`. Never put the avatar into `innerHTML`.
- Before `document.documentElement.appendChild(root)`, add `root.classList.add('owui-loading')`. In the `.finally` of `loadConfig`, call `root.classList.remove('owui-loading')`. This prevents a flash of default colors.

### 5.2 New SSE events

In `readStream` → `processEvent`, after the existing `data.widget` block, add:

```js
if (data.widget_status) {
	setStatus('Using tools');
	return;
}
if (data.widget_final) {
	fullText = data.widget_final.content || fullText;
	setMessageText(assistant, fullText);
	return;
}
if (data.widget_error) {
	assistant.classList.add('owui-error');
	fullText = data.widget_error.message || 'Something went wrong. Please try again.';
	setMessageText(assistant, fullText);
	return;
}
```

Keep the existing `extractDelta` path for `choices` deltas. When a delta arrives after a `widget_status`, call `setStatus('Typing')`.

### 5.3 CSS changes inside `injectStyles()`

Replace hard-coded values with variables. Every other rule stays as it is.

| Selector | Property → new value |
|---|---|
| `.owui-widget` | `right:var(--owui-offset-x,20px);bottom:var(--owui-offset-y,20px);font-family:var(--owui-font)` |
| `.owui-launcher` | `width:var(--owui-launcher-size,58px);height:var(--owui-launcher-size,58px);border-radius:var(--owui-launcher-radius,999px);background:var(--owui-primary,#111827);color:var(--owui-on-primary,#fff);overflow:hidden` |
| `.owui-panel` | `bottom:calc(var(--owui-launcher-size,58px) + 18px);width:min(var(--owui-panel-width,390px),calc(100vw - 32px));height:min(var(--owui-panel-height,640px),calc(100vh - 112px));border-radius:var(--owui-panel-radius,12px)` |
| `.owui-header` | `background:var(--owui-header-bg,#fff)` |
| `.owui-title` | `color:var(--owui-header-fg,#111827);font-size:calc(var(--owui-font-size,14px) + 1px)` |
| `.owui-subtitle` | `color:var(--owui-header-fg,#6b7280);opacity:.7` |
| `.owui-close` | `color:var(--owui-header-fg,#4b5563)` |
| `.owui-avatar` | `background:var(--owui-primary,#111827);color:var(--owui-on-primary,#fff);overflow:hidden` |
| `.owui-messages` | `background:var(--owui-bg,#fafafa)` |
| `.owui-bubble` | `font-size:var(--owui-font-size,14px);border-radius:var(--owui-bubble-radius,12px);background:var(--owui-assistant-bg,#fff);color:var(--owui-assistant-fg,#111827)` |
| `.owui-user .owui-bubble` | `background:var(--owui-user-bg,#111827);color:var(--owui-user-fg,#fff);border-color:var(--owui-user-bg,#111827)` |
| `.owui-input` | `font-size:var(--owui-font-size,14px)` |
| `.owui-input:focus` | `border-color:var(--owui-primary,#111827)` |
| `.owui-send` | `background:var(--owui-primary,#111827);color:var(--owui-on-primary,#fff)` |
| `.owui-send:hover:not(:disabled)` | `background:var(--owui-primary,#111827);filter:brightness(1.15)` |

`.owui-error .owui-bubble` keeps its fixed red colors. Error styling is not themeable.

Add these new rules:

```css
.owui-loading{visibility:hidden}
.owui-left{left:var(--owui-offset-x,20px);right:auto}
.owui-left .owui-panel{left:0;right:auto;transform-origin:bottom left}
.owui-hide-status .owui-status{display:none}
.owui-avatar-img{width:100%;height:100%;object-fit:cover;display:block}
.owui-avatar-img~svg{display:none}
.owui-launcher-img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;transition:opacity .16s ease}
.owui-launcher-has-img .owui-launcher-chat{display:none}
.owui-open .owui-launcher-img{opacity:0}
```

Inside the existing `@media (max-width:480px)` block, add the following. It overrides the mobile offsets; the panel takes the full width on phones no matter which theme is set:

```css
.owui-left{left:12px;right:auto}
.owui-left .owui-panel{left:-4px;right:auto}
```

---

## 6. Frontend API — `src/lib/apis/widgets/index.ts`

Add:

```ts
export type ChatWidgetTheme = {
	primary_color: string;
	primary_text_color: string;
	header_background_color: string;
	header_text_color: string;
	background_color: string;
	assistant_bubble_color: string;
	assistant_text_color: string;
	user_bubble_color: string;
	user_text_color: string;
	font_family: 'system' | 'arial' | 'verdana' | 'tahoma' | 'trebuchet' | 'georgia' | 'times' | 'courier';
	font_size: number;
	panel_radius: number;
	bubble_radius: number;
	panel_width: number;
	panel_height: number;
	launcher_shape: 'circle' | 'rounded' | 'square';
	launcher_size: number;
	launcher_icon: 'chat' | 'avatar';
	position: 'right' | 'left';
	offset_x: number;
	offset_y: number;
	avatar_url: string | null;
	header_title: string | null;
	header_subtitle: string | null;
	input_placeholder: string;
	show_status: boolean;
};

export const DEFAULT_WIDGET_THEME: ChatWidgetTheme = {
	primary_color: '#111827',
	primary_text_color: '#ffffff',
	header_background_color: '#ffffff',
	header_text_color: '#111827',
	background_color: '#fafafa',
	assistant_bubble_color: '#ffffff',
	assistant_text_color: '#111827',
	user_bubble_color: '#111827',
	user_text_color: '#ffffff',
	font_family: 'system',
	font_size: 14,
	panel_radius: 12,
	bubble_radius: 12,
	panel_width: 390,
	panel_height: 640,
	launcher_shape: 'circle',
	launcher_size: 58,
	launcher_icon: 'chat',
	position: 'right',
	offset_x: 20,
	offset_y: 20,
	avatar_url: null,
	header_title: null,
	header_subtitle: null,
	input_placeholder: 'Type a message',
	show_status: true
};

export const WIDGET_FONT_STACKS: Record<ChatWidgetTheme['font_family'], string> = {
	system: 'Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif',
	arial: 'Arial,Helvetica,sans-serif',
	verdana: 'Verdana,Geneva,sans-serif',
	tahoma: 'Tahoma,Geneva,sans-serif',
	trebuchet: '"Trebuchet MS",Helvetica,sans-serif',
	georgia: 'Georgia,serif',
	times: '"Times New Roman",Times,serif',
	courier: '"Courier New",Courier,monospace'
};
```

`DEFAULT_WIDGET_THEME` must match the backend defaults exactly, and `WIDGET_FONT_STACKS` must match `FONT_STACKS` in the embed script exactly. Add a comment above each one saying so.

Extend the existing types:
- `ChatWidget`: add `theme: ChatWidgetTheme; mcp_enabled: boolean; mcp_tool_ids: string[]; folder_id?: string | null;`
- `ChatWidgetForm`: add `theme: ChatWidgetTheme; mcp_enabled: boolean; mcp_tool_ids: string[];`
- `ChatWidgetSession`: add `chat_id?: string | null; chat_last_message_id?: string | null;`

---

## 7. Preview component — new `src/lib/components/workspace/ChatWidgetPreview.svelte`

A static, non-interactive mock of the open widget. It only shows what the theme looks like.

- Prop: `export let theme: ChatWidgetTheme; export let name: string; export let welcomeMessage: string | null;`
- Root: a `div` with `relative h-[560px] w-full overflow-hidden rounded-lg border border-gray-100 dark:border-gray-850 bg-gray-100 dark:bg-gray-900`. It stands in for the host page.
- Inside it, a panel absolutely positioned at `bottom: launcher_size + 18 + 12px`, at `right: 12px` (or `left: 12px` when `position === 'left'`). Its width is `min(theme.panel_width, 100% - 24px)`, its height is fixed at `420px` (preview only), and its radius is `theme.panel_radius`.
- Panel content, top to bottom:
  1. Header with `header_background_color`/`header_text_color`. It shows a 36×36 avatar box (`primary_color` background, `<img>` when `avatar_url`, otherwise the same chat SVG as the embed script), the title (`header_title || name || 'Chat'`), and, only when `show_status`, a green dot plus `header_subtitle || 'Online'`.
  2. Messages area with `background_color`. It shows an assistant bubble with `welcomeMessage || 'Hi! How can I help you?'`, then a user bubble `I have a question about my order.`, then an assistant bubble `Sure — what is your order number?`. Bubbles use the theme colors, `bubble_radius`, `font_size`, and `font-family: WIDGET_FONT_STACKS[font_family]`.
  3. Input row: a disabled textarea showing `input_placeholder` and a send button in `primary_color`.
- Launcher: absolutely positioned at `bottom: 12px`, at `right`/`left` `12px`. Its size is `launcher_size`, its radius comes from the circle/rounded/square map (`999px`/`16px`/`6px`), and its background is `primary_color`. It shows the avatar image when `launcher_icon === 'avatar' && avatar_url`, otherwise the chat SVG.
- Apply every theme value with inline `style=` attributes. Do not use Tailwind for theme values.
- Ignore `offset_x`/`offset_y` in the preview, and say so in a small gray note under the preview: "Offsets apply on the live site only."

---

## 8. Management UI — `src/lib/components/workspace/ChatWidgets.svelte`

### 8.1 State

- Import `getTools` from `$lib/apis/tools`, plus `DEFAULT_WIDGET_THEME`, `type ChatWidgetTheme` and `ChatWidgetPreview`.
- Add `let mcpServers: { id: string; name: string; description: string; authenticated?: boolean }[] = [];`
- In `onMount`, before `loadWidgets()`:
  ```ts
  const tools = await getTools(localStorage.token).catch(() => []);
  mcpServers = (tools ?? [])
  	.filter((tool) => tool.id.startsWith('server:mcp:'))
  	.map((tool) => ({ id: tool.id, name: tool.name, description: tool.meta?.description ?? '', authenticated: tool.authenticated }));
  ```
- Extend `form` in the initial value and in `resetForm` with: `mcp_enabled: false, mcp_tool_ids: [], theme: structuredClone(DEFAULT_WIDGET_THEME)`.
- In `editWidget`, add: `mcp_enabled: widget.mcp_enabled, mcp_tool_ids: [...(widget.mcp_tool_ids ?? [])], theme: { ...DEFAULT_WIDGET_THEME, ...(widget.theme ?? {}) }`.
- In `buildPayload`, add:
  ```ts
  mcp_tool_ids: form.mcp_enabled ? form.mcp_tool_ids : [],
  theme: {
  	...form.theme,
  	header_title: form.theme.header_title?.trim() || null,
  	header_subtitle: form.theme.header_subtitle?.trim() || null,
  	input_placeholder: form.theme.input_placeholder?.trim() || 'Type a message'
  }
  ```
- In `saveWidget`, add this check: if `form.mcp_enabled && form.mcp_tool_ids.length === 0`, then `toast.error($i18n.t('Select at least one MCP server'))` and return.

### 8.2 MCP tools block

In the right column (`<div class="space-y-3">`, the second one), insert directly after the "Allowed domains" `<label>`:

- A row styled like the existing "Enabled" row: title `MCP tools`, sub-text `Let this widget call MCP servers` / `Tools are off`, and a `<Switch bind:state={form.mcp_enabled} />`.
- When `form.mcp_enabled` is true, show a list under the row:
  - If `mcpServers.length === 0`: gray text `No MCP servers available. Ask an admin to add one in Settings → External Tools.`
  - Otherwise, one row per server with a checkbox bound to membership in `form.mcp_tool_ids` (toggle adds or removes the id), the server `name`, and the `description` (truncate, xs, gray).
  - If `authenticated === false`, disable the checkbox and show the amber xs text `Sign in to this server from a normal chat first`.
  - Ids in `form.mcp_tool_ids` that are not in `mcpServers` (removed or no longer accessible) are listed as rows with the text `Unavailable` and a remove button.

### 8.3 Appearance section

Add a new block inside the edit `<section>`, between the closing `</div>` of the `grid grid-cols-1 lg:grid-cols-2 gap-4 p-4` block and the footer `div` (the one with the Save button):

```
<div class="border-t border-gray-100 dark:border-gray-850 p-4">
  <div class="mb-3 text-sm font-medium">Appearance</div>
  <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
    <div class="space-y-4"> ...controls... </div>
    <ChatWidgetPreview theme={form.theme} name={form.name} welcomeMessage={form.welcome_message} />
  </div>
</div>
```

Controls, in this order and grouped under small gray xs headings:

**Avatar**
- A 48×48 rounded preview of `form.theme.avatar_url` (or a placeholder icon).
- An "Upload" button that opens a hidden `<input type="file" accept="image/png,image/jpeg,image/webp,image/gif">`. On change: if the file is > 5 MB, show `toast.error('Image is too large')`. Otherwise load it into an `Image`, draw it center-cropped (cover) on a 128×128 canvas, and set `form.theme.avatar_url = canvas.toDataURL('image/webp', 0.85)`. If the result is longer than 150000 characters, retry with quality `0.6`. If it is still too long, show a toast error and do not set it. Copy the load/canvas pattern from `src/lib/components/workspace/Models/ModelEditor.svelte` (around the `canvas.toDataURL` call).
- A "Remove" button (only shown when an avatar is set) that sets `avatar_url = null`.
- A select "Launcher icon": `Chat icon` → `chat`, `Avatar` → `avatar`. Disable it when no avatar is set.

**Colors** — a 2-column grid. Each item is a label plus `<input type="color">` bound to the field, plus a text input showing the hex value (also bound; on blur, revert the text to the bound value if it does not match `/^#[0-9a-fA-F]{6}$/`):
`Primary` (primary_color), `Text on primary` (primary_text_color), `Header background`, `Header text`, `Chat background` (background_color), `Assistant bubble`, `Assistant text`, `User bubble`, `User text`.
- A "Reset colors" text button that copies only the 9 color fields from `DEFAULT_WIDGET_THEME`.

**Text**
- Select `Font`: System, Arial, Verdana, Tahoma, Trebuchet, Georgia, Times New Roman, Courier → the enum values.
- Range `Font size` 12–20, step 1. Show the value in px next to it.
- Text input `Header title`, max 60, placeholder = the widget name.
- Text input `Header subtitle`, max 80, placeholder `Online`.
- Text input `Input placeholder`, max 120.
- Switch `Show status`.

**Layout** (all ranges show their value in px):
- Segmented buttons `Position`: Left / Right.
- Range `Horizontal offset` 0–120, `Vertical offset` 0–120.
- Range `Panel width` 300–480 step 10, `Panel height` 400–760 step 10.
- Range `Panel corner radius` 0–24, `Bubble corner radius` 0–24.
- Segmented buttons `Launcher shape`: Circle / Rounded / Square.
- Range `Launcher size` 44–72 step 2.

- A "Reset appearance" text button at the bottom that sets `form.theme = structuredClone(DEFAULT_WIDGET_THEME)`.

Bind every control directly to `form.theme.<field>`. Ranges need `bind:value` with numbers (Svelte `type="range"` binds numbers). The preview updates live because it receives `form.theme`.

### 8.4 Conversations panel

- In each conversation row, next to the delete button, add an "Open in chat" button. Show it only when `session.chat_id` is set. It is an `<a href="/c/{session.chat_id}">` with the existing `ChatBubble` icon and the tooltip `Open in chat`.
- In the selected conversation header, add the same link as a text button: `Open in chat`.
- Change the delete confirmation message to: `This will remove the widget conversation and its chat in your chat history.`

---

## 9. Testing checklist (manual)

MCP:
1. Create a widget with MCP off → ask something that needs a tool → no tool call; the answer streams.
2. Turn MCP on with no server selected → Save → error toast, and the backend returns 400 when called directly.
3. Select one MCP server → ask a question that triggers it → the widget status shows "Using tools" and the final answer includes the tool result. Open the chat in Open WebUI: the tool call and its output are visible.
4. Send `mcp_tool_ids: ["server:mcp:does-not-exist"]` through the API → 403.
5. Admin disables the MCP server → the widget still answers (without tools) and does not error.
6. MCP server with `session` auth → tool works (owner token is minted).

Appearance:
7. Change every theme field → the preview updates live → Save → reload the host page → the embed matches.
8. Position left plus offsets → correct on desktop; full width on a 375px viewport.
9. Upload a 4 MB JPEG → stored avatar is under 150 KB and shown in the header; launcher icon "Avatar" shows it in the launcher.
10. API: `primary_color: "red"` → 422. `avatar_url: "data:image/svg+xml;base64,..."` → 422. `font_size: 30` → 422.
11. An existing V1 widget (NULL theme) loads with default looks and no JS errors.
12. Public config response contains `theme` and does not contain `mcp_*`, `system_prompt`, `model_id` or `folder_id`.

Chat history:
13. First visitor message → the folder `Widget: <name>` appears in the owner's sidebar without a refresh, with one chat titled from the first message.
14. Five back-and-forth messages → one chat, correctly threaded; the model remembers earlier turns.
15. The visitor closes the tab mid-stream → the answer is still saved in both the chat and the widget conversation viewer.
16. The owner deletes the chat in Open WebUI → the next visitor message creates a new chat that contains the full previous history (backfill).
17. A V1 session with existing messages → next message creates a chat with backfilled history.
18. Delete a conversation from the widget page → the linked chat is also gone.
19. Delete the widget → its folder and chats remain.
20. Two visitors at the same time → two separate chats; no text from one appears in the other's stream.
21. Provider error (for example, invalid model key) → the widget shows the generic error; the chat and widget message store the real error.
