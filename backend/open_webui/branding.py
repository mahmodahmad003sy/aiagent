"""
Brand identity (name, links, ...) loaded from branding/branding.json.

The file is looked up at $BRANDING_CONFIG_PATH, then <repo root>/branding/branding.json
(which is /app/branding/branding.json in the Docker image). Keep this module free of
open_webui imports so env.py and constants.py can use it.
"""

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

_DEFAULTS = {
    'name': 'SmartLilac AI Studio',
    'short_name': 'SmartLilac',
    'description': 'SmartLilac AI Studio is a private, self-hosted AI workspace.',
    'copyright_holder': 'SmartLilac',
    'links': {},
}


def _load() -> dict:
    candidates = [
        os.environ.get('BRANDING_CONFIG_PATH'),
        Path(__file__).resolve().parents[2] / 'branding' / 'branding.json',
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            try:
                return {**_DEFAULTS, **json.loads(Path(candidate).read_text(encoding='utf-8'))}
            except Exception as e:
                log.error(f'Failed to load branding config {candidate}: {e}')
    return dict(_DEFAULTS)


BRANDING = _load()

BRAND_NAME: str = BRANDING['name']
BRAND_SHORT_NAME: str = BRANDING.get('short_name') or BRAND_NAME
BRAND_DESCRIPTION: str = BRANDING.get('description') or ''
BRAND_LINKS: dict = BRANDING.get('links') or {}
BRAND_WEBSITE: str = BRAND_LINKS.get('website') or ''
