"""Exercise the actual public asset handlers without opening the production DB."""
import ast
from pathlib import Path
import unittest
from urllib.parse import urljoin

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from starlette.responses import FileResponse

ROOT = Path(__file__).resolve().parents[1]


def asset_client():
    source = ROOT / 'backend/open_webui/routers/widgets.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    tree.body = [node for node in tree.body if getattr(node, 'name', '') in {
        'widget_embed_script', 'widget_markdown_script', 'widget_preview_script'}]
    router = APIRouter()
    namespace = dict(router=router, Path=Path, FileResponse=FileResponse, __file__=str(source))
    exec(compile(tree, str(source), 'exec'), namespace)
    app = FastAPI()
    app.include_router(router, prefix='/api/v1/widgets')
    return TestClient(app)


class AssetTests(unittest.TestCase):
    def test_embed_sibling_renderer_is_public_javascript(self):
        with asset_client() as client:
            embed_url = '/api/v1/widgets/public/embed.js'
            embed = client.get(embed_url)
            self.assertEqual(embed.status_code, 200)
            self.assertIn("new URL('markdown.js'", embed.text)
            renderer = client.get(urljoin(embed_url, 'markdown.js'), headers={'Origin': 'https://customer.example'})
            self.assertEqual(renderer.status_code, 200)
            self.assertTrue(renderer.headers['content-type'].startswith('text/javascript'))
            self.assertEqual(renderer.headers['cross-origin-resource-policy'], 'cross-origin')
            self.assertEqual(renderer.headers['x-content-type-options'], 'nosniff')
            self.assertEqual(renderer.headers['cache-control'], 'no-cache')
            self.assertEqual(renderer.content, (ROOT / 'backend/open_webui/static/widget/markdown.js').read_bytes())
            self.assertIn('mountApp', renderer.text)
            self.assertIn('OpenWebUIWidgetMarkdown', renderer.text)


if __name__ == '__main__':
    unittest.main()
