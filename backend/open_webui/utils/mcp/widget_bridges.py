"""Widget-specific adapter for installed Workspace MCP App Bridges.

Only parsed app data crosses to the browser, never the bridge wrapper or RPC token.
Capabilities are short-lived, session-bound, and reauthorized on every request.
"""
import json
import re
import secrets
import time

_apps = {}
TTL = 3600


def is_app_bridge(tool):
    if tool.id.startswith('server:'):
        return False
    meta = tool.meta.model_dump() if hasattr(tool.meta, 'model_dump') else (tool.meta or {})
    title = (meta.get('manifest') or {}).get('title', '')
    return any(re.search(r'\bmcp[\s_-]+app[\s_-]+bridge\b', str(value), re.I)
               for value in (tool.name, title))


def register_result(result, tool_id, session_id, turn):
    from starlette.responses import HTMLResponse
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], HTMLResponse):
        result = result[0]
    if not isinstance(result, HTMLResponse) or result.status_code != 200:
        return result
    if not turn or not getattr(turn, 'allow_apps', False):
        return 'This interactive app requires streaming. Enable streaming and try again.'
    try:
        body = result.body.decode('utf-8')
        if len(body) > 3_000_000:
            raise ValueError('App too large')
        match = re.search(r'\bvar\s+config\s*=\s*', body)
        config, _ = json.JSONDecoder().raw_decode(body[match.end():])
        html = config['appHtml']
        if not isinstance(html, str) or not html or len(html) > 2_000_000:
            raise ValueError('Invalid app')
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeError):
        return 'This MCP App Bridge returned an unsupported app format. Update the bridge and try again.'
    now = time.monotonic()
    for key, value in list(_apps.items()):
        if value['expires'] < now:
            _apps.pop(key, None)
    if len(_apps) >= 1024:
        return 'Too many active apps. Please try again later.'
    app_id = secrets.token_urlsafe(32)
    _apps[app_id] = dict(tool_id=tool_id, session_id=session_id, expires=now + TTL)
    turn.queue.put_nowait({'widget_bridge_app': {'id': app_id, 'html': html,
        'csp': ((config.get('hostCapabilities') or {}).get('sandbox') or {}).get('csp', {}),
        'toolInput': config.get('toolInput', {}), 'toolResult': config.get('toolResult', {})}})
    return 'The interactive MCP app is displayed in the widget.'


def get_app(app_id, session_id):
    app = _apps.get(app_id)
    if not app or app['session_id'] != session_id or app['expires'] < time.monotonic():
        raise ValueError('App expired')
    return app


def wrap_bridge(function, request, tool_id, message_id):
    from functools import wraps
    from inspect import isawaitable

    @wraps(function)
    async def call(*args, **kwargs):
        from open_webui.utils.widget_stream import get_widget_turn
        from starlette.responses import HTMLResponse

        # Some Workspace bridges emit the HTML separately and return only text.
        # Intercept only this selected bridge's emitter, never arbitrary chat HTML.
        emitter = kwargs.get('__event_emitter__')
        app_results = []
        if emitter is not None:
            async def emit(event):
                if isinstance(event, dict) and event.get('type') == 'embeds':
                    data = event.get('data') or {}
                    embeds = data.get('embeds', []) if isinstance(data, dict) else []
                    if isinstance(embeds, list):
                        for html in embeds[:8]:
                            if isinstance(html, str):
                                app_results.append(register_result(
                                    HTMLResponse(html), tool_id, request.state.widget_session_id,
                                    get_widget_turn(message_id)))
                    # Do not forward wrapper HTML (or its owner RPC token) to
                    # the normal emitter, chat history, or model context.
                    return
                return await emitter(event)
            kwargs['__event_emitter__'] = emit
        result = function(*args, **kwargs)
        if isawaitable(result):
            result = await result
        if app_results:
            return '\n'.join(dict.fromkeys(app_results))
        return register_result(result, tool_id, request.state.widget_session_id,
                               get_widget_turn(message_id))

    return call


async def call_bridge_app(module, method, params, request, user, tool_id, chat_id):
    """Supply a bridge's optional chat scope only from the verified session."""
    from inspect import signature

    handler = module._handle_app_request
    context = {}
    if 'chat_id' in signature(handler).parameters:
        if not chat_id:
            raise ValueError('Missing app conversation')
        context['chat_id'] = chat_id
    return await handler(method, params, request, user, tool_id, **context)
