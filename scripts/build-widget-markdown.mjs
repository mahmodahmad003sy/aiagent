import { build } from 'esbuild';
await build({
	entryPoints: ['scripts/widget-markdown.js'],
	outfile: 'backend/open_webui/static/widget/markdown.js',
	bundle: true,
	minify: true,
	format: 'iife',
	platform: 'browser',
	globalName: 'OpenWebUIWidgetMarkdown',
	target: ['es2020'],
	legalComments: 'eof'
});
