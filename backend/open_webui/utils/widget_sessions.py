"""Chat widget conversation lifecycle: ending a conversation and its tool-server logins.

Every widget visitor runs as the widget owner, so tool servers cannot tell visitors apart by user.
Each widget conversation is sent to tool servers as X-OpenWebUI-Widget-Session-Id (see
build_tool_server_headers), and a tool server that keeps logins keys them by that id. When a
conversation ends it can never be resumed, and every MCP server of the widget is told to drop
that conversation's login at <server url>/widget-sessions/end.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import aiohttp
from open_webui.env import AIOHTTP_CLIENT_SESSION_TOOL_SERVER_SSL
from open_webui.models.chat_widgets import (
    MCP_TOOL_ID_PREFIX,
    ChatWidgetModel,
    ChatWidgetSessions,
)
from open_webui.models.config import Config
from open_webui.utils.tools import build_tool_server_headers
from open_webui.utils.widget_secrets import redact_widget_session_secrets

log = logging.getLogger(__name__)

WIDGET_SESSION_END_PATH = '/widget-sessions/end'
WIDGET_SESSION_END_TIMEOUT = 5  # seconds
# When a page is hidden the visitor may be moving to another page of the site (the chat goes on)
# or closing the tab (the chat ends). The next page has this long to resume the conversation.
PAGE_HIDE_GRACE_SECONDS = 30
SESSION_END_REASONS = {
    'new_chat',
    'page_reload',
    'page_close',
    'page_unload',
    'idle_timeout',
    'visitor_mismatch',
    'deleted',
}

_background_tasks: set[asyncio.Task] = set()


def normalize_end_reason(reason: Optional[str]) -> str:
    return reason if reason in SESSION_END_REASONS else 'ended'


def is_hidden_past_grace(hidden_at: Optional[int], now: Optional[int] = None) -> bool:
    return bool(hidden_at) and hidden_at <= (now or int(time.time())) - PAGE_HIDE_GRACE_SECONDS


def _run_in_background(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _mcp_connection(server_id: str) -> Optional[dict]:
    for connection in await Config.get('tool_server.connections', []):
        if connection.get('type', '') == 'mcp' and (connection.get('info') or {}).get('id') == server_id:
            return connection
    return None


async def notify_tool_servers_session_end(
    request,
    widget: ChatWidgetModel,
    owner,
    session_id: str,
    reason: str,
) -> None:
    """Ask each MCP server of the widget to drop the login of one widget conversation."""
    for tool_id in widget.mcp_tool_ids or []:
        if not tool_id.startswith(MCP_TOOL_ID_PREFIX):
            continue
        server_id = tool_id[len(MCP_TOOL_ID_PREFIX) :]
        try:
            connection = await _mcp_connection(server_id)
            if not connection or not connection.get('url'):
                continue

            headers, cookies = await build_tool_server_headers(
                connection,
                request,
                owner,
                server_id=server_id,
                metadata={'widget_session_id': session_id},
            )
            headers['Content-Type'] = 'application/json'
            url = connection['url'].rstrip('/') + WIDGET_SESSION_END_PATH

            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=WIDGET_SESSION_END_TIMEOUT),
                trust_env=True,
            ) as http:
                async with http.post(
                    url,
                    json={'sessionId': session_id, 'reason': reason},
                    headers=headers,
                    cookies=cookies,
                    ssl=AIOHTTP_CLIENT_SESSION_TOOL_SERVER_SSL,
                ) as response:
                    if response.status == 200:
                        data = await response.json(content_type=None)
                        log.info(
                            'widget.session.mcp_logout server=%s session=%s reason=%s ended=%s',
                            server_id,
                            session_id,
                            reason,
                            (data or {}).get('ended'),
                        )
                    else:
                        # Servers without per-widget logins do not implement the endpoint.
                        log.debug(
                            'widget.session.mcp_logout_unsupported server=%s session=%s status=%s',
                            server_id,
                            session_id,
                            response.status,
                        )
        except Exception as e:
            log.warning('widget.session.mcp_logout_failed server=%s session=%s error=%s', server_id, session_id, e)


async def end_widget_session(
    request,
    widget: ChatWidgetModel,
    owner,
    session_id: str,
    chat_id: Optional[str],
    reason: str,
) -> bool:
    """Mark a widget conversation ended, mask its secrets and log it out of tool servers.

    The tool-server calls run in the background so page-unload beacons return at once.
    Returns False if the conversation was already ended.
    """
    reason = normalize_end_reason(reason)
    if not await ChatWidgetSessions.end_session(session_id, reason):
        return False

    log.info('widget.session.end widget=%s session=%s reason=%s', widget.id, session_id, reason)

    async def cleanup():
        try:
            await redact_widget_session_secrets(chat_id, widget.user_id, session_id, widget.id)
        except Exception as e:
            log.warning('widget.secrets.redact_failed session=%s error=%s', session_id, e)
        if widget.mcp_enabled:
            await notify_tool_servers_session_end(request, widget, owner, session_id, reason)

    _run_in_background(cleanup())
    return True


async def hide_widget_session(request, widget: ChatWidgetModel, owner, session_id: str) -> None:
    """The visitor's page went away. End the chat unless a page resumes it within the grace period.

    The pending end is also enforced lazily (see is_hidden_past_grace) in case this process
    restarts before the timer fires.
    """
    hidden_at = int(time.time())
    await ChatWidgetSessions.set_hidden_at(session_id, hidden_at)
    log.info('widget.session.hidden widget=%s session=%s grace=%ss', widget.id, session_id, PAGE_HIDE_GRACE_SECONDS)

    async def end_if_not_resumed():
        await asyncio.sleep(PAGE_HIDE_GRACE_SECONDS + 1)
        session = await ChatWidgetSessions.get_session_by_id(session_id)
        if session and not session.ended_at and session.hidden_at == hidden_at:
            await end_widget_session(request, widget, owner, session_id, session.chat_id, 'page_close')

    _run_in_background(end_if_not_resumed())
