"""Shared widget defaults, also imported by the setup UI as JSON."""
import json
from pathlib import Path

_defaults = json.loads((Path(__file__).resolve().parents[1] / 'static/widget/defaults.json').read_text(encoding='utf-8'))
DEFAULT_WIDGET_SYSTEM_PROMPT = _defaults['system_prompt']
DEFAULT_WIDGET_WELCOME_MESSAGE = _defaults['welcome_message']


def widget_system_prompt(custom: str | None) -> str:
    return (custom or '').strip() or DEFAULT_WIDGET_SYSTEM_PROMPT


def widget_welcome_message(custom: str | None) -> str:
    return (custom or '').strip() or DEFAULT_WIDGET_WELCOME_MESSAGE
