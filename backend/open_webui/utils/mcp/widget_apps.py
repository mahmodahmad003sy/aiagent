"""Ephemeral private MCP App interaction while a widget tool call is paused.

Credentials flow only through this queue to the existing MCP session. They never
become chat messages, model inputs, saved events, or log entries. In-process like
the existing widget stream; deployments must route a conversation to one worker.
"""
import asyncio
import secrets
from dataclasses import dataclass, field

APP_TIMEOUT = 300
_apps = {}


@dataclass
class PendingApp:
    session_id: str
    allowed_tools: set
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=2))
    closed: bool = False


async def submit(app_id, session_id, name, arguments):
    pending = _apps.get(app_id)
    if not pending or pending.closed or pending.session_id != session_id:
        raise ValueError('This sign-in form has closed. Please try your request again.')
    if (name not in pending.allowed_tools and name != '__cancel__') or not isinstance(arguments, dict):
        raise ValueError('This action is not available in the sign-in form.')
    if name == '__cancel__':
        # Mark closed immediately, including while the upstream login is in
        # flight. A successful late login must not resume a cancelled action.
        cancel_session(session_id)
        return {'cancelled': True}
    future = asyncio.get_running_loop().create_future()
    try:
        pending.queue.put_nowait((name, arguments, future))
    except asyncio.QueueFull:
        raise ValueError('Please wait for the current sign-in attempt.') from None
    return await asyncio.wait_for(future, timeout=60)


async def authenticate(client, turn, session_id, resource_uri):
    """Serve app calls on the original MCP task, then resume only after success."""
    allowed = {name for name, meta in client.app_tools.items()
               if meta.get('resourceUri') == resource_uri and 'app' in meta.get('visibility', ['model', 'app'])}
    if not allowed:
        return False
    resource = await client.read_resource(resource_uri)
    html = next((item.get('text') for item in resource.get('contents', [])
                 if item.get('mimeType') == 'text/html;profile=mcp-app'), None)
    if not html or len(html) > 2_000_000:
        return False
    app_id = secrets.token_urlsafe(32)
    pending = PendingApp(session_id, allowed)
    _apps[app_id] = pending
    turn.queue.put_nowait({'widget_app': {'id': app_id, 'html': html}})
    try:
        async with asyncio.timeout(APP_TIMEOUT):
            while True:
                name, arguments, future = await pending.queue.get()
                if future.cancelled():
                    continue
                if name is None:  # Conversation ended or user cancelled.
                    if not future.done():
                        future.set_result({'cancelled': True})
                    return False
                try:
                    response = await client.session.call_tool(name, arguments)
                    data = response.model_dump(mode='json')
                except Exception:
                    data = {'content': [{'type': 'text', 'text': 'Could not connect. Please try again.'}], 'isError': True}
                finally:
                    arguments.clear()
                if not future.done():
                    future.set_result(data)
                if pending.closed:
                    return False
                if not data.get('isError') and (data.get('structuredContent') or {}).get('authenticated') is True:
                    return True
    except TimeoutError:
        return False
    finally:
        pending.closed = True
        _apps.pop(app_id, None)
        while not pending.queue.empty():
            _, arguments, future = pending.queue.get_nowait()
            arguments.clear()
            if not future.done():
                future.set_result({'content': [{'type': 'text', 'text': 'Sign-in form closed.'}], 'isError': True})
        turn.queue.put_nowait({'widget_app_closed': {'id': app_id}})


def cancel_session(session_id):
    for pending in list(_apps.values()):
        if pending.session_id == session_id:
            pending.closed = True
            while not pending.queue.empty():
                _, arguments, future = pending.queue.get_nowait()
                arguments.clear()
                if not future.done():
                    future.cancel()
            pending.queue.put_nowait((None, {}, asyncio.get_running_loop().create_future()))
