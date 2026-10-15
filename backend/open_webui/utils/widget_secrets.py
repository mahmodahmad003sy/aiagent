"""Mask credentials that widget visitors type into the chat (MCP login passwords, OTP codes).

The model needs the real value for the one turn that calls the login tool, so nothing is masked
on the way in. Afterwards the values the model actually passed to login/OTP tools are collected
from the saved tool calls, and every occurrence of them is replaced in the owner's chat, the
chat_message rows and the widget message log.
"""

from __future__ import annotations

import html
import json
import logging
from typing import Any

from open_webui.models.chat_messages import ChatMessages
from open_webui.models.chat_widgets import ChatWidgetMessages
from open_webui.models.chats import Chats

log = logging.getLogger(__name__)

SECRET_MASK = '••••••'
MIN_SECRET_LENGTH = 4

# Argument names that always hold a secret, whatever the tool.
SECRET_ARG_NAMES = {'password', 'passwd', 'pass', 'passcode', 'otp', 'otp_code', 'otpcode', 'pin'}
# Argument names that hold a secret only in login/OTP tools ("code" is too generic elsewhere).
AUTH_TOOL_SECRET_ARG_NAMES = {'code', 'token', 'secret'}
AUTH_TOOL_MARKERS = ('login', 'otp', 'signin', 'sign_in', 'auth', 'verify')


def _is_auth_tool(name: str) -> bool:
    name = (name or '').lower()
    return any(marker in name for marker in AUTH_TOOL_MARKERS)


def _tool_call_args(item: dict) -> dict:
    arguments = item.get('arguments')
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _secrets_from_args(name: str, args: dict, found: set[str]) -> None:
    auth_tool = _is_auth_tool(name)
    for key, value in args.items():
        if not isinstance(value, str):
            continue
        value = value.strip()
        if len(value) < MIN_SECRET_LENGTH or value == SECRET_MASK:
            continue
        key = str(key).lower()
        if key in SECRET_ARG_NAMES or (auth_tool and key in AUTH_TOOL_SECRET_ARG_NAMES):
            found.add(value)


def collect_secrets(value: Any, found: set[str] | None = None) -> set[str]:
    """Find secret tool-call arguments anywhere in a chat / message structure."""
    found = set() if found is None else found
    if isinstance(value, dict):
        if value.get('type') == 'function_call':
            _secrets_from_args(str(value.get('name') or ''), _tool_call_args(value), found)
        function = value.get('function')
        if isinstance(function, dict) and 'arguments' in function:
            _secrets_from_args(str(function.get('name') or ''), _tool_call_args(function), found)
        for child in value.values():
            collect_secrets(child, found)
    elif isinstance(value, list):
        for child in value:
            collect_secrets(child, found)
    return found


def _replacements(secrets: set[str]) -> list[tuple[str, str]]:
    pairs: dict[str, str] = {}
    for secret in secrets:
        pairs[secret] = SECRET_MASK
        # The same value as it appears inside JSON-encoded tool arguments and HTML tool-call blocks.
        pairs[json.dumps(secret)[1:-1]] = SECRET_MASK
        pairs[html.escape(secret)] = SECRET_MASK
        pairs[html.escape(json.dumps(secret)[1:-1])] = SECRET_MASK
    # Longest first so a secret that contains another one is replaced whole.
    return sorted(((old, new) for old, new in pairs.items() if old), key=lambda pair: len(pair[0]), reverse=True)


def redact(value: Any, secrets: set[str]) -> tuple[Any, bool]:
    """Return (value with every secret replaced, whether anything changed)."""
    if not secrets:
        return value, False
    replacements = _replacements(secrets)

    def walk(item: Any) -> tuple[Any, bool]:
        if isinstance(item, str):
            new = item
            for old, mask in replacements:
                if old in new:
                    new = new.replace(old, mask)
            return new, new != item
        if isinstance(item, dict):
            changed = False
            result = {}
            for key, child in item.items():
                result[key], child_changed = walk(child)
                changed = changed or child_changed
            return result, changed
        if isinstance(item, list):
            changed = False
            result = []
            for child in item:
                new_child, child_changed = walk(child)
                result.append(new_child)
                changed = changed or child_changed
            return result, changed
        return item, False

    return walk(value)


async def redact_widget_session_secrets(
    chat_id: str | None,
    owner_id: str,
    session_id: str,
    widget_id: str,
) -> int:
    """Mask login secrets in one widget conversation. Returns how many records were rewritten."""
    if not chat_id:
        return 0

    chat = await Chats.get_chat_by_id(chat_id)
    if not chat or chat.user_id != owner_id:
        return 0

    messages_map = await Chats.get_messages_map_by_chat_id(chat_id) or {}
    secrets = collect_secrets(chat.chat)
    collect_secrets(messages_map, secrets)
    if not secrets:
        return 0

    rewritten = 0

    redacted_chat, chat_changed = redact(chat.chat, secrets)
    if chat_changed:
        patch = {key: redacted_chat[key] for key in ('title', 'history', 'messages') if key in redacted_chat}
        await Chats.update_chat_by_id(chat_id, patch, touch=False)
        rewritten += 1

    changed_messages = {}
    for message_id, message in messages_map.items():
        if not isinstance(message, dict):
            continue
        redacted_message, message_changed = redact(message, secrets)
        if message_changed:
            changed_messages[message_id] = redacted_message
    if changed_messages:
        await ChatMessages.upsert_messages(chat_id, owner_id, changed_messages)
        rewritten += len(changed_messages)

    for widget_message in await ChatWidgetMessages.get_messages_by_session_id_and_widget_id(session_id, widget_id):
        redacted_content, content_changed = redact(widget_message.content, secrets)
        redacted_error, error_changed = redact(widget_message.error, secrets)
        if content_changed or error_changed:
            await ChatWidgetMessages.update_message_content(
                widget_message.id,
                content=redacted_content,
                error=redacted_error,
            )
            rewritten += 1

    if rewritten:
        log.info(
            'widget.secrets.redacted session=%s chat=%s records=%d secrets=%d',
            session_id,
            chat_id,
            rewritten,
            len(secrets),
        )
    return rewritten
